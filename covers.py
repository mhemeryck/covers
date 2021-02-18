import argparse
import logging
import logging.config
import re
import sys
import threading
import time
import typing

import paho.mqtt.client as mqtt
import yaml

LOG_LEVEL = logging.INFO
LOG_CONFIG = dict(
    version=1,
    formatters={"default": {"format": "%(asctime)s - %(levelname)s - %(message)s"}},
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


class ACTION:
    """enum for actions"""

    COMMAND = "set"
    STATE = "state"


class OP:
    """enum for expected operations"""

    OPEN = "open"
    CLOSE = "close"


class ENTITY:
    """enum for types of entities"""

    INPUT = "input"
    RELAY = "relay"


class COVER_STATE:
    """enum to describe what the cover is currently doing"""

    OPENING = "opening"
    STILL = "still"
    CLOSING = "closing"


class PAYLOAD:
    """payload values"""

    ON = b"ON"
    OFF = b"OFF"


TOPIC_FORMAT = "{base_topic}/{entity_type}/{name}/{action}"
TOPIC_REGEX = re.compile(
    r"^(?P<base_topic>\w+)/(?P<entity_type>(input|relay))/(?P<name>\w+)/state$"
)


def cleanup(topic: str, on_time: int) -> None:
    """Shutdown the relay in a separate thread after max time"""
    time.sleep(on_time)
    client.publish(topic, PAYLOAD.OFF)


def on_message_input(
    client: mqtt.Client,
    userdata: typing.Union[None, typing.Dict],
    message: mqtt.MQTTMessage,
):
    """Callback for MQTT events"""
    logger.info(f"Handle input message {message.payload} for topic {message.topic}")

    # Ignore trailing edges
    if message.payload != PAYLOAD.ON:
        return

    # Match input
    match = TOPIC_REGEX.match(message.topic)

    # Nothing found, just break off
    if match is None:
        return

    name = match.group("name")
    cover_name = userdata["input_map"][name]["name"]
    relay_name = userdata["input_map"][name]["relay"]
    input_op = userdata["input_map"][name]["op"]

    # Get current state
    cover_state = userdata["cover_state"].get(cover_name)
    if not cover_state:
        return

    topic = TOPIC_FORMAT.format(
        base_topic=userdata["relays_base_topic"],
        entity_type=ENTITY.RELAY,
        name=relay_name,
        action=ACTION.COMMAND,
    )

    # Check transitions
    if input_op == OP.OPEN and cover_state == COVER_STATE.STILL:
        client.publish(topic, PAYLOAD.ON)
    elif input_op == OP.OPEN and cover_state == COVER_STATE.CLOSING:
        # Can't happen, just stop everything to be sure
        client.publish(topic, PAYLOAD.OFF)
        relay_name = userdata["config"][cover_name][OP.CLOSE]["relay"]
        topic = TOPIC_FORMAT.format(
            base_topic=userdata["relays_base_topic"],
            entity_type=ENTITY.RELAY,
            name=relay_name,
            action=ACTION.COMMAND,
        )
        client.publish(topic, PAYLOAD.OFF)
    elif input_op == OP.OPEN and cover_state == COVER_STATE.OPENING:
        client.publish(topic, PAYLOAD.OFF)
    elif input_op == OP.CLOSE and cover_state == COVER_STATE.STILL:
        client.publish(topic, PAYLOAD.ON)
    elif input_op == OP.CLOSE and cover_state == COVER_STATE.OPENING:
        # Can't happen, stop just to be sure
        client.publish(topic, PAYLOAD.OFF)
        relay_name = userdata["config"][cover_name][OP.OPEN]["relay"]
        topic = TOPIC_FORMAT.format(
            base_topic=userdata["relays_base_topic"],
            entity_type=ENTITY.RELAY,
            name=relay_name,
            action=ACTION.COMMAND,
        )
        client.publish(topic, PAYLOAD.OFF)
    elif input_op == OP.CLOSE and cover_state == COVER_STATE.CLOSING:
        client.publish(topic, PAYLOAD.OFF)


def on_message_relay(
    client: mqtt.Client,
    userdata: typing.Union[None, typing.Dict],
    message: mqtt.MQTTMessage,
):
    """Callback for relay MQTT events"""
    logger.info(f"Handle relay message {message.payload} for topic {message.topic}")

    # Match input
    match = TOPIC_REGEX.match(message.topic)

    # Nothing found, just break off
    if match is None:
        return

    name = match.group("name")
    cover_name = userdata["relay_map"][name]["name"]
    relay_op = userdata["relay_map"][name]["op"]

    # Update global state
    if relay_op == OP.OPEN and message.payload == PAYLOAD.ON:
        userdata["cover_state"][cover_name] = COVER_STATE.OPENING
    elif relay_op == OP.OPEN and message.payload == PAYLOAD.OFF:
        userdata["cover_state"][cover_name] = COVER_STATE.STILL
    elif relay_op == OP.CLOSE and message.payload == PAYLOAD.OFF:
        userdata["cover_state"][cover_name] = COVER_STATE.STILL
    elif relay_op == OP.CLOSE and message.payload == PAYLOAD.ON:
        userdata["cover_state"][cover_name] = COVER_STATE.CLOSING

    # Make sure the relays don't stay on too long, in a separate fire-and-forget thread
    if message.payload == PAYLOAD.ON:
        topic = TOPIC_FORMAT.format(
            base_topic=userdata["relays_base_topic"],
            entity_type=ENTITY.RELAY,
            name=name,
            action=ACTION.COMMAND,
        )
        threading.Thread(
            target=cleanup,
            args=(topic, userdata["on_time"]),
            daemon=True,
        ).start()

    return


def on_connect(
    client: mqtt.Client,
    userdata: typing.Union[None, typing.Dict],
    flags: typing.Dict,
    rc: int,
):
    """Callback for when MQTT connection to broker is set up"""
    logger.info("Subscribe to all state topics ...")
    for relay_name, relay_map in userdata["config"].items():
        for op, entity_map in relay_map.items():
            for entity_type, entity_name in entity_map.items():
                if entity_type == ENTITY.INPUT:
                    topic = TOPIC_FORMAT.format(
                        base_topic=userdata["inputs_base_topic"],
                        entity_type=entity_type,
                        name=entity_name,
                        action=ACTION.STATE,
                    )
                    client.message_callback_add(topic, on_message_input)
                elif entity_type == ENTITY.RELAY:
                    topic = TOPIC_FORMAT.format(
                        base_topic=userdata["relays_base_topic"],
                        entity_type=entity_type,
                        name=entity_name,
                        action=ACTION.STATE,
                    )
                    client.message_callback_add(topic, on_message_relay)
                else:
                    logger.warning(f"Unknown entity type {entity_type}")
                    return
                logger.info(
                    f"Subscribe to topic {topic} for {relay_name}-{op}-{entity_type}"
                )
                client.subscribe(topic)


def is_config_valid(
    config: typing.Dict[str, typing.Dict[str, typing.Dict[str, str]]]
) -> bool:
    """Check whether config is expected format"""
    for relay_name, relay_map in config.items():
        for op, entity_map in relay_map.items():
            if op not in (OP.OPEN, OP.CLOSE):
                logger.warning(f"Found invalid op {op} in config")
                return False
            for entity_type, entity_name in entity_map.items():
                if entity_type not in (ENTITY.INPUT, ENTITY.RELAY):
                    logger.warning(f"Found invalid entity type {entity_type} in config")
                    return False
        if relay_map[OP.OPEN][ENTITY.INPUT] == relay_map[OP.CLOSE][ENTITY.INPUT]:
            logger.warning(f"Found duplicate input entity in config for {relay_name}")
            return False
        if relay_map[OP.OPEN][ENTITY.RELAY] == relay_map[OP.CLOSE][ENTITY.RELAY]:
            logger.warning(f"Found duplicate relay entity in config for {relay_name}")
            return False
    return True


def input_map(
    config: typing.Dict[str, typing.Dict[str, typing.Dict[str, str]]]
) -> typing.Dict[str, typing.Dict[str, str]]:
    """Builds an easy mapping for inputs to the cover details"""
    mapping = {}
    for relay_name, relay_map in config.items():
        mapping[relay_map[OP.OPEN][ENTITY.INPUT]] = {
            "name": relay_name,
            "op": OP.OPEN,
            "relay": relay_map[OP.OPEN][ENTITY.RELAY],
        }
        mapping[relay_map[OP.CLOSE][ENTITY.INPUT]] = {
            "name": relay_name,
            "op": OP.CLOSE,
            "relay": relay_map[OP.CLOSE][ENTITY.RELAY],
        }
    return mapping


def relay_map(
    config: typing.Dict[str, typing.Dict[str, typing.Dict[str, str]]]
) -> typing.Dict[str, typing.Dict[str, str]]:
    """Builds an easy mapping for outputs to the cover details"""
    mapping = {}
    for relay_name, relay_map in config.items():
        mapping[relay_map[OP.OPEN][ENTITY.RELAY]] = {
            "name": relay_name,
            "op": OP.OPEN,
        }
        mapping[relay_map[OP.CLOSE][ENTITY.RELAY]] = {
            "name": relay_name,
            "op": OP.CLOSE,
        }
    return mapping


def init_cover_state(
    config: typing.Dict[str, typing.Dict[str, typing.Dict[str, str]]]
) -> typing.Dict[str, str]:
    """Keeps the global state of the covers"""
    return {cover_name: COVER_STATE.STILL for cover_name in config.keys()}


if __name__ == "__main__":
    # Parser
    parser = argparse.ArgumentParser()
    parser.add_argument("mqtt_host", help="MQTT broker host")
    parser.add_argument("config", help="YAML config file")
    parser.add_argument("inputs_base_topic", help="Base topic of device connecting to")
    parser.add_argument("relays_base_topic", default="shady", help="Relay base topic")
    parser.add_argument("--mqtt_port", type=int, default=1883)
    parser.add_argument(
        "--mqtt_client_id", help="Client ID to use for MQTT", default="covers"
    )
    parser.add_argument(
        "--on_time",
        type=int,
        default=30,
        help="Time in seconds the cover relays can on",
    )
    args = parser.parse_args()

    # read config
    with open(args.config, "r") as fh:
        config = yaml.safe_load(fh)

    # Validate
    if not is_config_valid(config):
        logger.warning("Found error in config, not starting ...")
        sys.exit(1)

    # MQTT initial setup
    logger.info(f"Connecting to MQTT broker {args.mqtt_host}")
    client = mqtt.Client(
        client_id=args.mqtt_client_id,
        clean_session=None,
        userdata={
            "relays_base_topic": args.relays_base_topic,
            "inputs_base_topic": args.inputs_base_topic,
            "config": config,
            "input_map": input_map(config),
            "relay_map": relay_map(config),
            "cover_state": init_cover_state(config),
            "on_time": args.on_time,
        },
    )
    client.on_connect = on_connect
    client.connect(args.mqtt_host, args.mqtt_port, 60)
    client.enable_logger(logger=logger)

    # Loop
    logger.info("Starting MQTT loop")
    client.loop_forever()
