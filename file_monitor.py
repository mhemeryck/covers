import asyncio
import typing

import aiofiles

FILENAME: str = "relay_state"
INTERVAL = 0.100


# class FileMonitor(collections.abc.AsyncGenerator):
#     def __init__(self, filename: str, interval: float) -> None:
#         self._filename = filename
#         self._interval = interval
#         self._state = False
#         self._previous = False

#     async def __aiter__(self) -> typing.Self:
#         return self

#     async def __anext__(self) -> bool:
#         async with aiofiles.open(self._filename, "r") as fh:
#             new = await fh.read()
#             match new:
#                 case "1\n":
#                     self._state = True
#                 case "0\n":
#                     self._state = False
#                 case _:
#                     print(new)
#                     pass
#             if self._state != self._previous:
#                 print(f"Found something new {self._previous} -> {self._state}")
#                 self._state = self._previous
#                 return self._state

#     async def asend(self, state: bool) -> None:
#         async with aiofiles.open(self._filename, mode="w") as fh:
#             data = "1" if state else "0"
#             data += "\n"
#             await fh.write(data)
#             await fh.flush()

#     async def athrow(self, typ, val=None, tb=None):
#         self._exception = typ(val)


async def file_monitor(filename: str, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, bool]:
    state = False
    old = False
    while True:
        async with aiofiles.open(filename, "r+") as fh:
            # read
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
            # write, if needed
            update = yield update
            print(f"got value update: {update}")
            if update != state:
                await fh.seek(0)
                await fh.write("1\n" if update else "0\n")
                await fh.flush()
                state = update


async def main() -> None:
    fm = file_monitor(FILENAME)
    # async for event in file_monitor(FILENAME):
    #     print(event)
    # file_monitor = FileMonitor(FILENAME, INTERVAL)

    async def reader():
        async for event in fm:
            print(f"Read an event: {event}")

    async def writer():
        await fm.asend(True)
        # await fm.asend(False)

    asyncio.gather(reader(), writer())


if __name__ == "__main__":
    asyncio.run(main())
