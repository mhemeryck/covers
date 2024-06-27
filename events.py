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


@dataclasses.dataclass
class Base:
    name: str
    state: bool

    def _event_type(self) -> EventType:
        raise NotADirectoryError()

    def identifier(self) -> Identifier:
        return Identifier("shady", self._event_type(), self.name)


@dataclasses.dataclass
class IO(Base):
    def _event_type(self) -> EventType:
        return EventType.IO


@dataclasses.dataclass
class PushButton(Base):
    def _event_type(self) -> EventType:
        return EventType.PUSH_BUTTON


@dataclasses.dataclass
class Light(Base):
    def _event_type(self) -> EventType:
        return EventType.LIGHT


Entity = PushButton | Light
Entry = IO | Entity


class Master:
    """Main master controlling flow of events"""

    def __init__(self) -> None:
        self._entries = [
            IO("di_1_01", False),
            PushButton("office", False),
            Light("office", False),
            IO("ro_2_01", False),
        ]


# Simple identifier-based mappings
_MAPPINGS: typing.Dict[Identifier, Identifier] = {
    Identifier("shady", EventType.IO, "di_1_01"): Identifier("shady", EventType.PUSH_BUTTON, "office"),
    Identifier("shady", EventType.PUSH_BUTTON, "office"): Identifier("shady", EventType.LIGHT, "office"),
    Identifier("shady", EventType.LIGHT, "office"): Identifier("shady", EventType.IO, "ro_2_01"),
}


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


async def process(q: asyncio.Queue[Event], n: int) -> None:
    master = Master()
    while True:
        event = await q.get()
        match event:
            case Event(ident, state):
                logger.debug("%d - incoming ident %s - state %s", n, ident, state)
                if found := _MAPPINGS.get(ident):
                    try:
                        entry = next(filter(lambda e: e.identifier() == found, master._entries))
                    except StopIteration:
                        pass
                    else:
                        # TODO: deal with event here!
                        pass

                    logger.debug("%d - outgoing ident %s - state %s", n, found, state)
                    await q.put(Event(found, state))
        q.task_done()


async def run() -> None:
    queue = asyncio.Queue()
    await asyncio.gather(
        *[
            qemit(queue),
            process(queue, 0),
            process(queue, 1),
        ]
    )


if __name__ == "__main__":
    asyncio.run(run())
