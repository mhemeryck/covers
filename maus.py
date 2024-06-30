import abc
import asyncio
import dataclasses
import enum
import logging
import pathlib
import re
import typing

import aiofiles
import watchfiles
from aiofiles.threadpool.text import AsyncTextIOWrapper

# TODO: get config from CLI
WATCH_DIRECTORY = "./fixtures"

logger = logging.getLogger(__name__)


# TODO: move to global logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s - %(funcName)s] %(message)s",
)


class EventType(enum.StrEnum):
    IO = enum.auto()
    PUSH_BUTTON = enum.auto()
    LIGHT = enum.auto()


@dataclasses.dataclass(frozen=True)
class Identifier:
    device_name: str
    name: str
    event_type: EventType


@dataclasses.dataclass
class Event:
    identifier: Identifier
    state: bool


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


class IO:
    PAYLOAD_ON = "1"
    PAYLOAD_OFF = "0"

    def __init__(self, filename: str, state: bool) -> None:
        self._filename = filename
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


@dataclasses.dataclass
class PushButton(EventHandler, HasIdentifier):
    name: str
    state: bool

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        match event:
            case Event(Identifier(_, _, EventType.IO), payload):
                self.state = payload
                return [Event(self.identifier(), payload)]
            case _:
                logger.warning("%s can't handle event %s", self, event)
                return []

    def identifier(self) -> Identifier:
        return Identifier("shady", self.name, EventType.PUSH_BUTTON)


@dataclasses.dataclass
class Light(EventHandler, HasIdentifier):
    name: str
    state: bool

    async def handle(self, event: Event) -> typing.Iterable[Event]:
        match event:
            case Event(Identifier(_, _, EventType.PUSH_BUTTON), payload):
                self.state = payload
                return [Event(self.identifier(), payload)]
            case _:
                logger.warning("%s can't handle event %s", self, event)
                return []

    def identifier(self) -> Identifier:
        return Identifier("shady", self.name, EventType.LIGHT)


Entity = PushButton | Light
Entry = IO | Entity


class FileMonitor(EventHandler):
    """Functionality specifically for SysFS integration"""

    _FILENAME_PATTERN = re.compile(
        r"(.*)/io_group(1|2|3)/(?P<device_fmt>di|do|ro)_(?P<io_group>1|2|3)_(?P<number>\d{2})/(di|do|ro)_value$"
    )

    def __init__(self, folder: str) -> None:
        self._folder = folder
        self._io_for_filename, self._io_for_ident, self._ident_for_filename = self._crawl(pathlib.Path(folder))

    @staticmethod
    def _crawl(
        folder: pathlib.Path,
    ) -> typing.Tuple[
        typing.Mapping[pathlib.Path, IO],
        typing.Mapping[Identifier, IO],
        typing.Mapping[pathlib.Path, Identifier],
    ]:
        """
        3 mappings to support all sorts of lookups:
        1. absolute path to IO
        1. identifier to IO
        1. absolute path to identifier
        """
        io_for_filename = {}
        io_for_ident = {}
        ident_for_filename = {}
        for root, _, files in folder.walk():
            for f in files:
                filename = root / f
                if (match := FileMonitor._FILENAME_PATTERN.match(str(filename))) and match is not None:
                    full_path = filename.resolve()
                    name = "{device_fmt}_{io_group}_{number}".format(**match.groupdict())
                    ident = Identifier("shady", name, EventType.IO)

                    io_for_filename[full_path] = io_for_ident[ident] = IO(str(full_path), False)
                    # TODO: fix device name
                    ident_for_filename[full_path] = ident
        return io_for_filename, io_for_ident, ident_for_filename

    @staticmethod
    def io_filter(change: watchfiles.Change, path: str) -> bool:
        return change == watchfiles.Change.modified and any(
            path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
        )

    async def watch(self) -> typing.AsyncGenerator[Event, None]:
        async for event in watchfiles.awatch(str(self._folder), force_polling=True, watch_filter=FileMonitor.io_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                # logger.debug(filename)
                full_path = pathlib.Path(filename).resolve()
                io = self._io_for_filename[full_path]
                # logger.debug(device)
                state = await io.read()
                # logger.debug(device)
                ident = self._ident_for_filename[full_path]
                yield Event(ident, state)

    async def run(self, queue: asyncio.Queue[Event]) -> None:
        async for event in self.watch():
            await queue.put(event)

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
            Identifier("shady", "di_1_01", EventType.IO): Identifier("shady", "office", EventType.PUSH_BUTTON),
            Identifier("shady", "office", EventType.PUSH_BUTTON): Identifier("shady", "office", EventType.LIGHT),
            Identifier("shady", "office", EventType.LIGHT): Identifier("shady", "ro_2_01", EventType.IO),
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
    file_monitor = FileMonitor(WATCH_DIRECTORY)
    await asyncio.gather(
        *[
            maus.run(),
            file_monitor.run(queue),
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())
