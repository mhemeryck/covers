import argparse
import asyncio
import contextlib
import enum
import logging
import logging.config
import re
import sys
import typing

import asyncio_mqtt
import yaml

LOG_LEVEL = logging.INFO
LOG_CONFIG = dict(
    version=1,
    formatters={"default": {"format": "%(asctime)s - %(levelname)s - %(name)s - %(message)s"}},
    handlers={
        "stream": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "level": LOG_LEVEL,
        }
    },
    root={"handlers": ["stream"], "level": LOG_LEVEL},
)
logging.config.dictConfig(LOG_CONFIG)
logger = logging.getLogger(__name__)

TOPIC_REGEX = re.compile(
    r"^(?P<base_topic>\w+)/(?P<entity>(input|relay|cover))/(?P<name>\w+)/(set|state)$"
)
TOPIC_FORMAT = "{base_topic}/{entity}/{name}/{action}"


class Entity(enum.Enum):
    """MQTT entity"""

    COVER = "cover"
    RELAY = "relay"


class Action(enum.Enum):
    """Actions on MQTT topic"""

    COMMAND = "set"
    STATE = "state"
    POSITION = "position"


class Payload(enum.Enum):
    ON = b"ON"
    OFF = b"OFF"
    OPEN = b"OPEN"
    CLOSE = b"CLOSE"
    STOP = b"STOP"


class Shade:
    OPENING = "opening"
    CLOSING = "closing"
    STOPPED = "stopped"

    OPEN = "open"
    CLOSED = "closed"

    _DIRECTION_OPENING = 1
    _DIRECTION_CLOSING = -1
    _DIRECTION_STOPPED = 0

    def __init__(
        self,
        cover: str,
        open_relay: str,
        close_relay: str,
        mqtt_host: str,
        mqtt_base_topic_cover: str,
        mqtt_base_topic_relay: str,
        sleep_time: float = 0.5,
        max_time: float = 30.0,
        max_position: int = 100,
    ):
        self.cover = cover
        self.open_relay = open_relay
        self.close_relay = close_relay
        self._open_relay_state = False
        self._close_relay_state = False
        self._state = Shade.STOPPED

        # Position tracking
        self.position = max_position
        self._max_time = max_time
        self._max_position = max_position
        self._direction = self._DIRECTION_STOPPED
        self._direction_lock = asyncio.Lock()
        self._sleep_time = sleep_time
        self._increment = int(
            round(self._max_position * self._sleep_time / self._max_time)
        )

        self._open_relay_lock = asyncio.Lock()
        self._close_relay_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        self._mqtt_host = mqtt_host
        self._mqtt_base_topic_cover = mqtt_base_topic_cover
        self._mqtt_base_topic_relay = mqtt_base_topic_relay

        # Logger setup
        self._logger = logging.getLogger(self.cover)

        self._topics()

    def _topics(self) -> None:
        """Calculate and assign MQTT topics required for shade"""
        self._logger.debug("initialize the topics")

        self._cover_command_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_cover,
            entity=Entity.COVER.value,
            name=self.cover,
            action=Action.COMMAND.value,
        )
        self._logger.debug(f"cover command topic {self._cover_command_topic}")
        self._cover_state_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_cover,
            entity=Entity.COVER.value,
            name=self.cover,
            action=Action.STATE.value,
        )
        self._logger.debug(f"cover state topic {self._cover_state_topic}")
        self._cover_position_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_cover,
            entity=Entity.COVER.value,
            name=self.cover,
            action=Action.POSITION.value,
        )
        self._logger.debug(f"cover position topic {self._cover_position_topic}")
        self._open_relay_state_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_relay,
            entity=Entity.RELAY.value,
            name=self.open_relay,
            action=Action.STATE.value,
        )
        self._logger.debug(f"open relay state topic {self._open_relay_state_topic}")
        self._close_relay_state_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_relay,
            entity=Entity.RELAY.value,
            name=self.close_relay,
            action=Action.STATE.value,
        )
        self._logger.debug(f"close relay state topic {self._close_relay_state_topic}")
        # Wildcard here
        self._relay_state_filter = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_relay,
            entity=Entity.RELAY.value,
            name="+",
            action=Action.STATE.value,
        )
        self._logger.debug(f"relay state topic {self._relay_state_filter}")
        self._open_relay_command_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_relay,
            entity=Entity.RELAY.value,
            name=self.open_relay,
            action=Action.COMMAND.value,
        )
        self._logger.debug(f"open relay command topic {self._open_relay_state_topic}")
        self._close_relay_command_topic = TOPIC_FORMAT.format(
            base_topic=self._mqtt_base_topic_relay,
            entity=Entity.RELAY.value,
            name=self.close_relay,
            action=Action.COMMAND.value,
        )
        self._logger.debug(f"close relay command topic {self._close_relay_state_topic}")

    # Position tracking
    async def run(self) -> None:
        """Main async coroutine"""
        self._logger.info("start tracking ...")
        async with contextlib.AsyncExitStack() as stack:
            # Connects to the MQTT host using the context manager
            self._mqtt_client = asyncio_mqtt.Client(self._mqtt_host)
            await stack.enter_async_context(self._mqtt_client)

            await asyncio.gather(
                self._subscribe_cover(),
                self._subscribe_relays(),
                self._track_position(),
            )

    async def _subscribe_relays(self) -> None:
        """Subscribe to and handle relay state topic updates"""
        self._logger.debug("subscribe to and handle relay state topics")
        await asyncio.gather(
            self._mqtt_client.subscribe(self._open_relay_state_topic),
            self._mqtt_client.subscribe(self._close_relay_state_topic),
        )
        async with self._mqtt_client.filtered_messages(
            self._relay_state_filter
        ) as messages:
            async for message in messages:
                if message.topic not in (
                    self._open_relay_state_topic,
                    self._close_relay_state_topic,
                ):
                    continue
                self._logger.info(f"relays message {message.topic} -- {message.payload.decode()}")
                # Update relay state
                if message.topic == self._open_relay_state_topic:
                    async with self._open_relay_lock:
                        if message.payload == Payload.ON.value:
                            self._open_relay_state = True
                        elif message.payload == Payload.OFF.value:
                            self._open_relay_state = False
                elif message.topic == self._close_relay_state_topic:
                    async with self._close_relay_lock:
                        if message.payload == Payload.ON.value:
                            self._close_relay_state = True
                        elif message.payload == Payload.OFF.value:
                            self._close_relay_state = False

    async def _subscribe_cover(self) -> None:
        """Subscribe to and handle cover command topic"""
        self._logger.debug("subscribe to and handle cover command topic")
        await self._mqtt_client.subscribe(self._cover_command_topic)
        async with self._mqtt_client.filtered_messages(
            self._cover_command_topic
        ) as messages:
            async for message in messages:
                if message.topic != self._cover_command_topic:
                    continue
                self._logger.info(f"cover message {message.topic} -- {message.payload.decode()}")
                if message.payload == Payload.OPEN.value:
                    await self.set_open()
                elif message.payload == Payload.STOP.value:
                    await self.set_stop()
                elif message.payload == Payload.CLOSE.value:
                    await self.set_close()

    async def _track_position(self) -> None:
        self._logger.debug("start tracking position")
        while True:
            new_position = int(self.position + self._direction * self._increment)
            if not 0 <= new_position <= self._max_position:
                self._direction = Shade._DIRECTION_STOPPED
                new_position = max([min([self._max_position, new_position]), 0])

            self.position = new_position
            self._logger.debug(f"position: {self.position}")
            if (
                0 < self.position < self._max_position
                and self._direction != Shade._DIRECTION_STOPPED
            ):
                await self._mqtt_client.publish(
                    self._cover_position_topic,
                    str(self.position).encode(),
                )

            # Push out event for the edges
            if self.position == 0 and self._state != Shade.STOPPED:
                # Stop everything
                await asyncio.gather(
                    self.set_stop(),
                    self._mqtt_client.publish(
                        self._cover_position_topic,
                        str(self.position).encode(),
                    ),
                    self._mqtt_client.publish(
                        self._cover_state_topic,
                        Shade.CLOSED,
                    ),
                )
            elif self.position == self._max_position and self._state != Shade.STOPPED:
                await asyncio.gather(
                    self.set_stop(),
                    self._mqtt_client.publish(
                        self._cover_position_topic,
                        str(self.position).encode(),
                    ),
                    self._mqtt_client.publish(
                        self._cover_state_topic,
                        Shade.OPEN,
                    ),
                )

            await asyncio.sleep(self._sleep_time)

    async def _position_open(self) -> None:
        """Start counter for open direction"""
        async with self._direction_lock:
            self._direction = Shade._DIRECTION_OPENING

    async def _position_close(self) -> None:
        """Start counter for close direction"""
        async with self._direction_lock:
            self._direction = Shade._DIRECTION_CLOSING

    async def _position_stop(self) -> None:
        """Stop counter"""
        async with self._direction_lock:
            self._direction = Shade._DIRECTION_STOPPED

    # Commands: incoming commands for state transitions
    async def set_open(self) -> None:
        """Open shade from command"""
        if self._state == Shade.STOPPED:
            self._logger.debug("open on stopped state")
            await asyncio.gather(
                self._set_close_relay_off(),
                self._set_open_relay_on(),
                self._state_opening(),
            )
        elif self._state == Shade.CLOSING:
            self._logger.debug("open on closing state")
            # First stop everything
            await asyncio.gather(
                self._set_close_relay_off(),
                self._set_open_relay_off(),
                self._state_stopped(),
            )
            # Then, open again
            await asyncio.gather(
                self._set_close_relay_off(),
                self._set_open_relay_on(),
                self._state_opening(),
            )

    async def set_stop(self) -> None:
        """Stop shade from command"""
        await asyncio.gather(
            self._set_close_relay_off(),
            self._set_open_relay_off(),
            self._state_stopped(),
        )

    async def set_close(self) -> None:
        """Close shade from command"""
        if self._state == Shade.STOPPED:
            self._logger.debug("close on stopped state")
            await asyncio.gather(
                self._set_close_relay_on(),
                self._set_open_relay_off(),
                self._state_closing(),
            )
        elif self._state == Shade.OPENING:
            self._logger.debug("close on opening state")
            # First stop everything
            await asyncio.gather(
                self._set_close_relay_off(),
                self._set_open_relay_off(),
                self._state_stopped(),
            )
            # Then, close again
            await asyncio.gather(
                self._set_close_relay_on(),
                self._set_open_relay_off(),
                self._state_closing(),
            )

    # Relays

    # Incoming state: wait for relay states to have been updated
    async def _state_opening(self) -> None:
        while not (self._open_relay_state and not self._close_relay_state):
            self._logger.debug(
                f"open relay state {self._open_relay_state} -- close relay state {self._close_relay_state}"
            )
            await asyncio.sleep(self._sleep_time)

        async with self._state_lock:
            old_state = self._state
            self._state = Shade.OPENING
            self._logger.debug(f"state update from {old_state} to {self._state}")
            await asyncio.gather(
                self._position_open(),
                self._mqtt_client.publish(
                    self._cover_state_topic,
                    Shade.OPENING,
                ),
            )

    async def _state_stopped(self) -> None:
        while not (not self._open_relay_state and not self._close_relay_state):
            self._logger.debug(
                f"open relay state {self._open_relay_state} -- close relay state {self._close_relay_state}"
            )
            await asyncio.sleep(self._sleep_time)

        async with self._state_lock:
            old_state = self._state
            self._state = Shade.STOPPED
            self._logger.debug(f"state update from {old_state} to {self._state}")
            await self._position_stop()

    async def _state_closing(self) -> None:
        while not (not self._open_relay_state and self._close_relay_state):
            self._logger.debug(
                f"open relay state {self._open_relay_state} -- close relay state {self._close_relay_state}"
            )
            await asyncio.sleep(self._sleep_time)

        async with self._state_lock:
            old_state = self._state
            self._state = Shade.CLOSING
            self._logger.debug(f"state update from {old_state} to {self._state}")
            await asyncio.gather(
                self._position_close(),
                self._mqtt_client.publish(
                    self._cover_state_topic,
                    Shade.CLOSING,
                ),
            )

    # Incoming state: update the relay state from MQTT
    async def _set_open_relay_on(self) -> None:
        """Push state update for open relay on"""
        self._logger.info("set open relay on")
        await self._mqtt_client.publish(
            self._open_relay_command_topic,
            Payload.ON.value,
        )

    async def _set_open_relay_off(self) -> None:
        """Push state update for open relay off"""
        self._logger.info("set open relay off")
        await self._mqtt_client.publish(
            self._open_relay_command_topic,
            Payload.OFF.value,
        )

    async def _set_close_relay_on(self) -> None:
        """Push state update for close relay on"""
        self._logger.info("set close relay on")
        await self._mqtt_client.publish(
            self._close_relay_command_topic,
            Payload.ON.value,
        )

    async def _set_close_relay_off(self) -> None:
        """Push state update for close relay off"""
        self._logger.info("set close relay off")
        await self._mqtt_client.publish(
            self._close_relay_command_topic,
            Payload.OFF.value,
        )


def _shades_from_config(
    config: typing.Dict[str, typing.Dict[str, str]],
    host: str,
    cover_base: str,
    relay_base: str,
) -> typing.Iterable[Shade]:
    """Build list of shades from yaml config file"""
    return [
        Shade(name, relays["open"], relays["close"], host, cover_base, relay_base)
        for name, relays in config.items()
    ]


def _is_config_valid(config: typing.Dict[str, typing.Dict[str, str]]) -> bool:
    """Validate YAML file config"""
    relays = []
    for name, relay_map in config.items():
        for op in relay_map.keys():
            if op not in ("open", "close"):
                logger.warning(f"op {op} is not one of open, close")
                return False
        if relay_map["open"] == relay_map["close"]:
            logger.warning(f"found duplicate relay for cover {name}")
            return False
        for relay in relay_map.values():
            if relay in relays:
                logger.warning(f"Non-unique relay name {relay}")
                return False
            else:
                relays.append(relay)
    return True


async def main(shades: typing.Iterable[Shade]) -> None:
    await asyncio.gather(*(shade.run() for shade in shades))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("config", help="Config file mapping covers to relays")
    parser.add_argument("--mqtt_host", help="MQTT broker host", default="shuttle.lan")
    parser.add_argument("--mqtt_base_topic_cover", default="homeassistant")
    parser.add_argument("--mqtt_base_topic_relay", default="shady")
    args = parser.parse_args()

    logger.info("building shades from config")

    with open(args.config, "r") as fh:
        config = yaml.safe_load(fh)

    if not _is_config_valid(config):
        logger.warning("invalid config, stopping")
        sys.exit(1)

    shades = _shades_from_config(
        config,
        args.mqtt_host,
        args.mqtt_base_topic_cover,
        args.mqtt_base_topic_relay,
    )
    logger.info("start monitoring shades")
    asyncio.run(main(shades))
