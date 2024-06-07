import asyncio
import aiofiles
import os
import re
import typing

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


class Device:
    def __init__(self, filename: str) -> None:
        self._filename = filename

    async def read(self) -> typing.AsyncGenerator[bool, None]:
        async for event in watchfiles.awatch(self._filename, force_polling=True):
            yield event.difference()

    async def write(self, state: bool) -> None:
        async with aiofiles.open(self._filename, "wb") as fh:
            payload = b"1\n" if state else b"0\n"
            await fh.write(payload)


async def writer(device) -> None:
    await asyncio.sleep(2)
    await device.write(True)
    await asyncio.sleep(2)
    await device.write(False)


async def reader(device) -> None:
    async for event in device.read():
        print(event)


async def main() -> None:
    filenames = crawl(WATCH_DIRECTORY)
    jobs = []
    for filename in filenames:
        device = Device(filename)
        jobs += [writer(device), reader(device)]
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
