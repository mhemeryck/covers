import asyncio
import typing

import aiofiles

FILENAME: str = "relay_state"
INTERVAL = 0.100


class FileMonitor:
    # def __init__(self, filename: str) -> None:
    def __init__(self) -> None:
        pass

    @classmethod
    async def create(cls, filename: str) -> typing.Self:
        self = cls()
        self._filename = filename
        self._state = False
        self._previous = False
        self._file_lock = asyncio.Lock()
        self._file_handle = await aiofiles.open(self._filename, "r+")
        return self

    async def read(self, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
        state = False
        old = False
        while True:
            async with self._file_lock:
                # read
                await self._file_handle.seek(0)
                new = await self._file_handle.read()
                match new:
                    case "1\n":
                        state = True
                    case "0\n":
                        state = False
                    case _:
                        print(f"something went wrong, state: {new}")
                        pass
                if state != old:
                    print(f"Found something new {old} -> {state}")
                    old = state
                    yield state
                await asyncio.sleep(interval)

    async def write(self, state: bool) -> None:
        async with self._file_lock:
            data = "1\n" if state else "0\n"
            await self._file_handle.seek(0)
            await self._file_handle.write(data)
            await self._file_handle.flush()


#     async def athrow(self, typ, val=None, tb=None):
#         self._exception = typ(val)


# async def file_monitor(filename: str, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
#     state = False
#     old = False
#     while True:
#         async with aiofiles.open(filename, "r+") as fh:
#             # read
#             new = await fh.read()
#             match new:
#                 case "1\n":
#                     state = True
#                 case "0\n":
#                     state = False
#                 case _:
#                     print(state)
#                     pass
#             if state != old:
#                 print(f"Found something new {old} -> {state}")
#                 old = state
#                 yield state
#             await asyncio.sleep(interval)


async def main() -> None:
    fm = await FileMonitor.create(FILENAME)

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
