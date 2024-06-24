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


async def process(q: asyncio.Queue[Event]) -> None:
    while True:
        event = await q.get()
        match event:
            case Event(ident, state):
                logger.debug("incoming ident %s - state %s", ident, state)
                if found := _MAPPINGS.get(ident):
                    logger.debug("outgoing ident %s - state %s", found, state)
                    await q.put(Event(found, state))
        q.task_done()


async def run() -> None:
    queue = asyncio.Queue()
    await asyncio.gather(*[qemit(queue), process(queue)])


if __name__ == "__main__":
    asyncio.run(run())
