import asyncio
import dataclasses
import enum
import typing


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


async def process() -> None:
    """Just print whatever's happening"""
    async for event in emit():
        match event:
            case Event(ident, state):
                print(ident, state)
                found = _MAPPINGS.get(ident)
                print(found)


async def run() -> None:
    await process()


if __name__ == "__main__":
    asyncio.run(run())
