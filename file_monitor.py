import asyncio
import typing

import aiofiles

FILENAME: str = "relay_state"
INTERVAL = 0.100


class FileMonitor:
    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._state = False
        self._previous = False
        self._file_lock = asyncio.Lock()

    async def read(self, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
        state = False
        old = False
        while True:
            async with aiofiles.open(self._filename, "r") as fh:
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

    async def write(self, state: bool) -> None:
        async with self._file_lock:
            async with aiofiles.open(self._filename, "w") as fh:
                data = "1\n" if state else "0\n"
                await fh.write(data)


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


async def file_monitor(filename: str, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
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


async def main() -> None:
    fm = FileMonitor(FILENAME)

    async def reader():
        async for event in fm.read():
            print(f"Read an event: {event}")

    async def writer():
        await asyncio.sleep(2)
        await fm.write(True)
        await asyncio.sleep(2)
        await fm.write(False)
        await asyncio.sleep(2)

    await asyncio.gather(reader(), writer())


if __name__ == "__main__":
    asyncio.run(main())
