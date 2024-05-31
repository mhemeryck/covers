import asyncio
import typing

import aiofiles

FILENAME: str = "relay_state"
INTERVAL = 0.100


async def file_monitor(filename: str, interval: float = INTERVAL) -> typing.AsyncIterator[bool]:
    state = False
    old = False
    while True:
        async with aiofiles.open(filename, "r") as fh:
            new = await fh.read()
            match new:
                case "1\n":
                    state = True
                case "0\n":
                    state = False
                case _:
                    print(state)
                    pass
            if state != old:
                print(f"Found something new {old} -> {state}")
                old = state
                yield state
            await asyncio.sleep(interval)


async def main() -> None:
    async for event in file_monitor(FILENAME):
        print(event)


if __name__ == "__main__":
    asyncio.run(main())
