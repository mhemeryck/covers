import abc
import asyncio
import dataclasses
import enum
import logging
import pathlib
import re
import typing

import aiofiles
import pydantic
import watchfiles
import yaml
from aiofiles.threadpool.text import AsyncTextIOWrapper

# TODO: get config from CLI
WATCH_DIRECTORY = "./fixtures"
CONFIG_FILE = "./config2.yaml"

logger = logging.getLogger(__name__)


# TODO: move to global logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s - %(funcName)s] %(message)s",
)


class EntryConfig(pydantic.BaseModel):
    name: str
    io: str


class CoverConfig(pydantic.BaseModel):
    name: str
    motor_up: str
    motor_down: str


class EntityConfig(pydantic.BaseModel):
    push_buttons: typing.List[EntryConfig]
    lights: typing.List[EntryConfig]
    covers: typing.List[CoverConfig]


class LightAutomation(pydantic.BaseModel):
    name: str
    push_button: str
    light: str


class CoverAutomation(pydantic.BaseModel):
    name: str
    push_button_up: str
    push_button_down: str
    cover: str


class AutomationConfig(pydantic.BaseModel):
    lights: typing.List[LightAutomation]
    covers: typing.List[CoverAutomation]


class Config(pydantic.BaseModel):
    entities: EntityConfig
    automations: AutomationConfig

    @classmethod
    def from_filename(cls, filename: str) -> typing.Self:
        with open(filename, "rb") as fh:
            data = yaml.safe_load(fh)
            return cls(**data)

    def is_valid(self) -> bool:
        """
        Simplified check: just validate whether all entities in the automations match up with the entities before
        """
        push_buttons = [p.name for p in self.entities.push_buttons]
        lights = [light.name for light in self.entities.lights]
        covers = [c.name for c in self.entities.covers]

        # check light automations
        for a in self.automations.lights:
            if a.push_button not in push_buttons:
                return False
            if a.light not in lights:
                return False

        # Check cover automations
        for a in self.automations.covers:
            if a.push_button_up not in push_buttons:
                return False
            if a.push_button_down not in push_buttons:
                return False
            if a.cover not in covers:
                return False

        return True


filename = "./config2.yaml"
config = Config.from_filename(filename)
assert config.is_valid()


class EventType(enum.StrEnum):
    IO = enum.auto()
    PUSH_BUTTON = enum.auto()
    LIGHT = enum.auto()


class Name:
    def __init__(self, *parts: str) -> None:
        self._parts = parts

    def __repr__(self) -> str:
        return self.name()

    def __eq__(self, other: typing.Self) -> bool:
        return self._parts == other._parts

    def __hash__(self):
        return hash(self._parts)

    def name(self) -> str:
        return "/".join(self._parts)

    def parts(self) -> typing.Iterable[str]:
        return self._parts


@dataclasses.dataclass(frozen=True)
class Identifier:
    name: Name
    event_type: EventType


@dataclasses.dataclass
class Event:
    identifier: Identifier
    payload: typing.Any


class EventHandler(typing.Protocol):
    @abc.abstractmethod
    async def handle(self, event: Event) -> typing.Iterable[Event]:
        """
        Handle an incoming event.

        The handler can responed with a series of other events to be processed in turn.
        """


class HasIdentifier(typing.Protocol):
    @abc.abstractmethod
    def identifier(self) -> Identifier:
        """Can generate an identifier"""


class IO(HasIdentifier):
    PAYLOAD_ON = "1"
    PAYLOAD_OFF = "0"

    def __init__(self, filename: str, name: Name, state: bool) -> None:
        self._filename = filename
        self._name = name
        self._state = state

        self._state_lock = asyncio.Lock()
        self._read_file_handle = None
        self._write_file_handle = None

    async def _get_write_file_handle(self) -> AsyncTextIOWrapper:
        if self._write_file_handle is None:
            self._write_file_handle = await aiofiles.open(self._filename, "w")
        return self._write_file_handle

    async def _get_read_file_handle(self) -> AsyncTextIOWrapper:
        if self._read_file_handle is None:
            self._read_file_handle = await aiofiles.open(self._filename, "r")
        return self._read_file_handle

    async def read(self) -> bool:
        async with self._state_lock:
            logger.debug("reading %s", self)
            fh = await self._get_read_file_handle()
            await fh.seek(0)
            data = await fh.read(1)
            logger.debug(data)
            match data:
                case IO.PAYLOAD_ON:
                    self._state = True
                case IO.PAYLOAD_OFF:
                    self._state = False
                case _:
                    logger.warning("Could not match state: %s", data)
            return self._state

    async def write(self, state: bool) -> None:
        payload = IO.PAYLOAD_ON if state else IO.PAYLOAD_OFF
        logger.debug(payload)
        async with self._state_lock:
            logger.debug("writing %s", self)
            fh = await self._get_write_file_handle()
            await fh.seek(0)
            await fh.write(f"{payload}\n")
            await fh.flush()

    def identifier(self) -> Identifier:
        return Identifier(self._name, EventType.IO)


@dataclasses.dataclass
class PushButton(EventHandler, HasIdentifier):
    name: str
    state: bool

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        match event:
            case Event(Identifier(_, EventType.IO), payload):
                self.state = payload
                return [Event(self.identifier(), payload)]
            case _:
                logger.warning("%s can't handle event %s", self, event)
                return []

    def identifier(self) -> Identifier:
        return Identifier(Name(self.name), EventType.PUSH_BUTTON)


@dataclasses.dataclass
class Light(EventHandler, HasIdentifier):
    name: str
    state: bool

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        match event:
            case Event(Identifier(_, EventType.PUSH_BUTTON), payload):
                self.state = payload
                return [Event(self.identifier(), payload)]
            case _:
                logger.warning("%s can't handle event %s", self, event)
                return []

    def identifier(self) -> Identifier:
        return Identifier(Name(self.name), EventType.LIGHT)


Entity = PushButton | Light
Entry = IO | Entity


class HasIdentifierMapping(typing.Protocol):
    @abc.abstractmethod
    def identifier_to_entries(self) -> typing.Mapping[Identifier, Entry]:
        """
        Exposes a mapping that the manager holds between a given event identifier and an entry.

        The rationale is so that this can be used to link events and handlers globally together
        """


class IOManager(EventHandler, HasIdentifierMapping):
    """Functionality specifically for SysFS integration"""

    _FILENAME_PATTERN = re.compile(
        r"(.*)/io_group(1|2|3)/(?P<device_fmt>di|do|ro)_(?P<io_group>1|2|3)_(?P<number>\d{2})/(di|do|ro)_value$"
    )

    def __init__(self, device_name: str, folder: str, queue: asyncio.Queue[Event]) -> None:
        self._device_name = device_name
        self._folder = folder
        self._io_for_filename, self._io_for_ident = self._crawl(device_name, pathlib.Path(folder))
        self._queue = queue

    @staticmethod
    def _crawl(
        device_name: str,
        folder: pathlib.Path,
    ) -> typing.Tuple[typing.Mapping[pathlib.Path, IO], typing.Mapping[Identifier, IO]]:
        """
        2 mappings to support all sorts of lookups:
        1. absolute path to IO
        1. identifier to IO
        """
        io_for_filename = {}
        io_for_ident = {}
        ident_for_filename = {}
        for root, _, files in folder.walk():
            for f in files:
                filename = root / f
                if (match := IOManager._FILENAME_PATTERN.match(str(filename))) and match is not None:
                    full_path = filename.resolve()
                    name = "{device_fmt}_{io_group}_{number}".format(**match.groupdict())
                    io_for_filename[full_path] = io = IO(str(full_path), Name(device_name, name), False)
                    ident_for_filename[full_path] = io.identifier()
        return io_for_filename, io_for_ident

    @staticmethod
    def io_filter(change: watchfiles.Change, path: str) -> bool:
        return change == watchfiles.Change.modified and any(
            path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
        )

    async def watch(self) -> typing.AsyncGenerator[Event, None]:
        async for event in watchfiles.awatch(str(self._folder), force_polling=True, watch_filter=IOManager.io_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                full_path = pathlib.Path(filename).resolve()
                try:
                    io = self._io_for_filename[full_path]
                except KeyError:
                    logger.warning("Could not retrieve IO for %s", full_path)
                else:
                    state = await io.read()
                    yield Event(io.identifier(), state)

    async def run(self) -> None:
        async for event in self.watch():
            await self._queue.put(event)

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        match event:
            case Event(ident, payload):
                try:
                    io = self._io_for_ident[ident]
                except KeyError:
                    logger.warning("no IO for given event %s", event)
                else:
                    await io.write(payload)
            case _:
                logger.warning("%s can't handle event %s", self, event)
        return []

    def identifier_to_entries(self) -> typing.Mapping[Identifier, Entry]:
        return self._io_for_ident


class EntityManager(EventHandler, HasIdentifierMapping):
    def __init__(self, config_file: str) -> None:
        self._config = Config.from_filename(config_file)

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        return await super().handle(event)

    def identifier_to_entries(self) -> typing.Mapping[Identifier, Entry]:
        return super().identifier_to_entries()


class Maus:
    """Main controller for the flow of events"""

    def __init__(self, queue: asyncio.Queue[Event]) -> None:
        # TODO: get config from elsewhere
        self._entries = [
            # IO("di_1_01", False),
            PushButton("office", False),
            Light("office", False),
            # IO("ro_2_01", False),
        ]
        # TODO: config from elsewhere
        # TODO: support for N-to-1 mappings
        self._config: typing.Mapping[Identifier, Identifier] = {
            Identifier(Name("shady", "di_1_01"), EventType.IO): Identifier(Name("office"), EventType.PUSH_BUTTON),
            Identifier(Name("office"), EventType.PUSH_BUTTON): Identifier(Name("office"), EventType.LIGHT),
            Identifier(Name("office"), EventType.LIGHT): Identifier(Name("shady", "ro_2_01"), EventType.IO),
        }
        self._queue = queue

    def _next_handlers(self, event: Event) -> typing.Generator[EventHandler, None, None]:
        """Find the set of entries for a given event based in the identifier and the config"""
        match event:
            case Event(ident, _):
                try:
                    next_ident = self._config[ident]
                except KeyError:
                    return
                for entry in self._entries:
                    if entry.identifier() == next_ident:
                        yield entry

    async def run(self) -> None:
        """
        Handle all events coming from the queue:
        - find the next handlers
        - have the event handled by the entry handlers
        - the entry handler will put things again on the queue -- to be handled again
        """

        async def push(event: Event):
            await self._queue.put(event)

        while True:
            event = await self._queue.get()
            logger.debug("got event %s", event)
            for handler in self._next_handlers(event):
                logger.debug("next handler: %s", handler)
                next_events = await handler.handle(event)
                await asyncio.gather(
                    *(push(e) for e in next_events),
                )
            self._queue.task_done()


async def main() -> None:
    queue = asyncio.Queue()
    maus = Maus(queue)
    io_manager = IOManager("shady", WATCH_DIRECTORY, queue)
    entity_manager = EntityManager(CONFIG_FILE)
    await asyncio.gather(
        *[
            maus.run(),
            io_manager.run(),
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())
