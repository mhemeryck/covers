import asyncio
import aiofiles
import os
import re
import typing
from aiofiles.threadpool.text import AsyncTextIOWrapper


import watchfiles

WATCH_DIRECTORY = "./fixtures"

_FILENAME_PATTERN = re.compile(
    r"(.*)/io_group(1|2|3)/(?P<device_fmt>di|do|ro)_(?P<io_group>1|2|3)_(?P<number>\d{2})/(di|do|ro)_value$"
)


def crawl(folder: str) -> typing.List[str]:
    result = []
    for root, _, files in os.walk(folder):
        for f in files:
            filename = os.path.join(root, f)
            filename = os.path.normpath(filename)
            if _FILENAME_PATTERN.match(filename) is not None:
                result.append(filename)
    return result


def only_modified(change: watchfiles.Change, path: str) -> bool:
    return change == watchfiles.Change.modified


class Device:
    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._state = False
        self._state_lock = asyncio.Lock()
        self._file_handle = None

    async def _get_file_handle(self) -> AsyncTextIOWrapper:
        if self._file_handle is None:
            self._file_handle = await aiofiles.open(self._filename, "wb+")
        return self._file_handle

    async def _read_state(self) -> bool:
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            data = await fh.read()
        self._state = data == b"1\n"
        return self._state

    async def _write_state(self, state: bool) -> None:
        # early return
        if state == self._state:
            return
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            payload = b"1\n" if state else b"0\n"
            await fh.write(payload)
        self._state = state

    async def read(self) -> typing.AsyncGenerator[bool, None]:
        async for _ in watchfiles.awatch(self._filename, force_polling=True, watch_filter=only_modified):
            yield await self._read_state()

    async def write(self, state: bool) -> None:
        await self._write_state(state)


async def writer(device) -> None:
    await asyncio.sleep(2)
    await device.write(True)
    await asyncio.sleep(2)
    await device.write(False)


async def reader(device) -> None:
    async for event in device.read():
        print(device._filename, event)


async def main() -> None:
    filenames = crawl(WATCH_DIRECTORY)
    jobs = []
    for filename in filenames:
        device = Device(filename)
        jobs += [writer(device), reader(device)]
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
