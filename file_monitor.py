import asyncio
import os
import re
import typing

import aiofiles
import watchfiles
from aiofiles.threadpool.text import AsyncTextIOWrapper

WATCH_DIRECTORY = "./fixtures"

_FILENAME_PATTERN = re.compile(
    r"(.*)/io_group(1|2|3)/(?P<device_fmt>di|do|ro)_(?P<io_group>1|2|3)_(?P<number>\d{2})/(di|do|ro)_value$"
)


def crawl(folder: str) -> typing.List[str]:
    result = []
    for root, _, files in os.walk(folder):
        for f in files:
            filename = os.path.join(root, f)
            filename = os.path.abspath(filename)
            if _FILENAME_PATTERN.match(filename) is not None:
                result.append(filename)
    return result


def file_filter(change: watchfiles.Change, path: str) -> bool:
    return change == watchfiles.Change.modified and any(
        path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
    )


async def watcher() -> typing.AsyncGenerator[bool, None]:
    async for event in watchfiles.awatch(WATCH_DIRECTORY, force_polling=True, watch_filter=file_filter):
        print(event)
        for _, filename in tuple(event):
            # ((_, filename),) = tuple(event)
            print(filename)
            device = devices()[os.path.abspath(filename)]
            print(device, device._state)
            # yield await self._read_state()
            new = await device._read_state()
            print(device, new, device._state)


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
        print("reading")
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            data = await fh.read()
            self._state = data == b"1\n"
            return self._state

    async def _write_state(self, state: bool) -> None:
        payload = b"1\n" if state else b"0\n"
        print(payload)
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            n = await fh.write(payload)
            print("written", n, payload)
        await self._read_state()
        print("finished writing state", state)

    # async def read(self) -> typing.AsyncGenerator[bool, None]:
    #     async for _ in watchfiles.awatch(self._filename, force_polling=True):
    #         print("events", self._filename)
    #         yield await self._read_state()

    async def write(self, state: bool) -> None:
        await self._write_state(state)


_DEVICES: typing.Dict[str, Device] = {}


def devices() -> typing.Dict[str, Device]:
    global _DEVICES
    if not _DEVICES:
        _DEVICES = {filename: Device(filename) for filename in crawl(WATCH_DIRECTORY)}
    return _DEVICES


async def writer(device) -> None:
    print("sleeping")
    await asyncio.sleep(2)
    print("trigger to true")
    await device.write(True)
    print("sleeping")
    await asyncio.sleep(2)
    print("trigger to false")
    print("device state", device._state)
    await device.write(False)
    print("sleeping")
    await asyncio.sleep(2)
    print("trigger to true")
    await device.write(True)


async def reader(device) -> None:
    async for event in device.read():
        print(device._filename, event, device._state)


async def main() -> None:
    filenames = crawl(WATCH_DIRECTORY)
    jobs = []
    for filename in filenames:
        device = devices()[filename]
        jobs += [writer(device)]
    jobs.append(watcher())
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
