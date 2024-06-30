import abc
import asyncio
import dataclasses
import enum
import logging
import pathlib
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
    async def handle(self, event: Event) -> None:
        """Handle an incoming event"""


class HasIdentifier(typing.Protocol):
    @abc.abstractmethod
    def identifier(self) -> Identifier:
        """Can generate an identifier"""


class IO(EventHandler, HasIdentifier):
    PAYLOAD_ON = "1"
    PAYLOAD_OFF = "0"

    queue: asyncio.Queue
    name: str
    state: bool

    def __init__(self, queue: asyncio.Queue[Event], filename: str, state: bool) -> None:
        self._queue = queue
        self._filename = filename
        self._state = state

        self._state_lock = asyncio.Lock()
        self._read_file_handle = None
        self._write_file_handle = None

    async def handle(self, event: Event) -> None:
        match event:
            case Event(Identifier(_, EventType.LIGHT, _), payload):
                self.state = payload
                logger.debug("writing to do something to the light!")
                await self.write(payload)
                await self._queue.put(Event(self.identifier(), payload))
            case _:
                logger.warning("%s can't handle event %s", self, event)

    def identifier(self) -> Identifier:
        # TODO: fix device identifier
        return Identifier("shady", self.name, EventType.IO)

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
            # await fh.writelines([payload])
            await fh.flush()


@dataclasses.dataclass
class PushButton(EventHandler, HasIdentifier):
    queue: asyncio.Queue
    name: str
    state: bool

    async def handle(self, event: Event) -> None:
        match event:
            case Event(Identifier(_, EventType.IO, _), payload):
                self.state = payload
                await self.queue.put(Event(self.identifier(), payload))
            case _:
                logger.warning("%s can't handle event %s", self, event)

    def identifier(self) -> Identifier:
        return Identifier("shady", self.name, EventType.PUSH_BUTTON)


@dataclasses.dataclass
class Light(EventHandler, HasIdentifier):
    queue: asyncio.Queue
    name: str
    state: bool

    async def handle(self, event: Event) -> None:
        match event:
            case Event(Identifier(_, EventType.PUSH_BUTTON, _), payload):
                self.state = payload
                await self.queue.put(Event(self.identifier(), payload))
            case _:
                logger.warning("%s can't handle event %s", self, event)

    def identifier(self) -> Identifier:
        return Identifier("shady", self.name, EventType.LIGHT)


Entity = PushButton | Light
Entry = IO | Entity


class FileMonitorMixin:
    """Functionality specifically for SysFS integration"""


    def _crawl(self, folder: pathlib.Path)

    @staticmethod
    def device_filter(change: watchfiles.Change, path: str) -> bool:
        return change == watchfiles.Change.modified and any(
            path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
        )

    async def read(self, folder: pathlib.Path) -> typing.AsyncGenerator[Event, None]:
        async for event in watchfiles.awatch(folder, force_polling=True, watch_filter=FileMonitorMixin.device_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                # logger.debug(filename)
                device = self._devices_for_filename[os.path.abspath(filename)]
                io: IO
                # logger.debug(device)
                state = await device.read()
                # logger.debug(device)
                yield Event(io.identifier(), state)


class Maus:
    """Main controller for the flow of events"""

    def __init__(self, queue: asyncio.Queue[Event]) -> None:
        # TODO: get config from elsewhere
        self._entries = [
            IO(queue, "di_1_01", False),
            PushButton(queue, "office", False),
            Light(queue, "office", False),
            IO(queue, "ro_2_01", False),
        ]
        # TODO: config from elsewhere
        # TODO: support for N-to-1 mappings
        self._config: typing.Mapping[Identifier, Identifier] = {
            Identifier("shady", "di_1_01", EventType.IO): Identifier("shady", "office", EventType.PUSH_BUTTON),
            Identifier("shady", "office", EventType.PUSH_BUTTON): Identifier("shady", "office", EventType.LIGHT),
            Identifier("shady", "office", EventType.LIGHT): Identifier("shady", "ro_2_01", EventType.IO),
        }
        self._queue = queue

    def _next_handlers(self, event: Event) -> typing.Generator[Entry, None, None]:
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
        while True:
            event = await self._queue.get()
            for handler in self._next_handlers(event):
                logger.debug("next handler: %s", handler)
                await handler.handle(event)
            self._queue.task_done()
