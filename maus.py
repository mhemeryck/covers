import abc
import asyncio
import dataclasses
import enum
import logging
import typing

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


@dataclasses.dataclass
class IO(EventHandler, HasIdentifier):
    queue: asyncio.Queue
    name: str
    state: bool

    async def handle(self, event: Event) -> None:
        match event:
            case Event(Identifier(_, EventType.LIGHT, _), payload):
                self.state = payload
                # At this point we probably also need to write something back ...
                await self.queue.put(Event(self.identifier(), payload))
                logger.debug("writing to do something to the light!")
            case _:
                logger.warning("%s can't handle event %s", self, event)

    def identifier(self) -> Identifier:
        # TODO: fix device identifier
        return Identifier("shady", self.name, EventType.IO)


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
