import abc
import asyncio
import dataclasses
import enum
import logging
import typing

logger = logging.getLogger(__name__)

# TODO: move to global logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s - %(funcName)s] %(message)s",
)


class EventType(enum.StrEnum):
    BASE = enum.auto()
    IO = enum.auto()
    PUSH_BUTTON = enum.auto()
    LIGHT = enum.auto()


@dataclasses.dataclass(frozen=True)
class Identifier:
    device_name: str
    event_type: EventType
    name: str


@dataclasses.dataclass
class Event:
    identifier: Identifier
    state: bool


class EventHandler(typing.Protocol):
    @abc.abstractmethod
    def handle(self, event: Event) -> None:
        """Handle an incoming event"""


class HasIdentifier(typing.Protocol):
    @abc.abstractmethod
    def identifier(self) -> Identifier:
        """Can generate an identifier"""


@dataclasses.dataclass
class IO(EventHandler, HasIdentifier):
    name: str
    state: bool

    def handle(self, event: Event) -> None:
        pass

    def identifier(self) -> Identifier:
        # TODO: fix device identifier
        return Identifier("shady", EventType.IO, self.name)


@dataclasses.dataclass
class PushButton(EventHandler, HasIdentifier):
    name: str
    state: bool

    def handle(self, event: Event) -> None:
        pass

    def identifier(self) -> Identifier:
        return Identifier("shady", EventType.PUSH_BUTTON, self.name)


@dataclasses.dataclass
class Light(EventHandler, HasIdentifier):
    name: str
    state: bool

    def handle(self, event: Event) -> None:
        pass

    def identifier(self) -> Identifier:
        return Identifier("shady", EventType.LIGHT, self.name)


Entity = PushButton | Light
Entry = IO | Entity

# Simple identifier-based mappings
_MAPPINGS: typing.Dict[Identifier, Identifier] = {
    Identifier("shady", EventType.IO, "di_1_01"): Identifier("shady", EventType.PUSH_BUTTON, "office"),
    Identifier("shady", EventType.PUSH_BUTTON, "office"): Identifier("shady", EventType.LIGHT, "office"),
    Identifier("shady", EventType.LIGHT, "office"): Identifier("shady", EventType.IO, "ro_2_01"),
}


class Master:
    """Main master controlling flow of events"""

    def __init__(self, queue: asyncio.Queue[Event]) -> None:
        self._entries = [
            IO("di_1_01", False),
            PushButton("office", False),
            Light("office", False),
            IO("ro_2_01", False),
        ]
        self._queue = queue

    async def run(self) -> None:
        while True:
            event = await self._queue.get()
            match event:
                case Event(ident, state):
                    logger.debug("incoming ident %s - state %s", ident, state)
                    if found := _MAPPINGS.get(ident):
                        try:
                            entry = next(filter(lambda e: e.identifier() == found, self._entries))
                        except StopIteration:
                            pass
                        else:
                            # TODO: deal with event here!
                            logger.debug("%s", entry)

                        logger.debug("outgoing ident %s - state %s", found, state)
                        await self._queue.put(Event(found, state))
            self._queue.task_done()


async def emit() -> typing.AsyncGenerator[Event, None]:
    """Randomly emit some IO events to check how we could process those"""
    count = 0
    while True:
        yield Event(
            Identifier("shady", EventType.IO, "di_1_01"),
            count == 1,
        )
        count = (count + 1) % 2
        await asyncio.sleep(1)


async def qemit(q: asyncio.Queue[Event]) -> None:
    count = 0
    while count < 10:
        device_name = "shady" if count != 7 else "slim"
        await q.put(
            Event(
                Identifier(device_name, EventType.IO, "di_1_01"),
                count % 2 == 0,
            )
        )
        count += 1
        await asyncio.sleep(1)


# async def process(q: asyncio.Queue[Event], n: int) -> None:
#     master = Master()
#     while True:
#         event = await q.get()
#         match event:
#             case Event(ident, state):
#                 logger.debug("%d - incoming ident %s - state %s", n, ident, state)
#                 if found := _MAPPINGS.get(ident):
#                     try:
#                         entry = next(filter(lambda e: e.identifier() == found, master._entries))
#                     except StopIteration:
#                         pass
#                     else:
#                         # TODO: deal with event here!
#                         pass

#                     logger.debug("%d - outgoing ident %s - state %s", n, found, state)
#                     await q.put(Event(found, state))
#         q.task_done()


async def run() -> None:
    queue = asyncio.Queue()
    master = Master(queue)
    await asyncio.gather(
        *[
            qemit(queue),
            master.run(),
        ]
    )


if __name__ == "__main__":
    asyncio.run(run())
