import asyncio
import logging
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

logger = logging.getLogger(__name__)

# TODO: move to global logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def file_filter(change: watchfiles.Change, path: str) -> bool:
    return change == watchfiles.Change.modified and any(
        path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
    )


class Watcher:
    """Data structure to monitor all devices"""

    def __init__(self, folder: str) -> None:
        self._folder = folder
        self._devices: typing.Dict[str, Device] = {}

    def crawl(self, folder: str) -> typing.List[str]:
        result = []
        for root, _, files in os.walk(folder):
            for f in files:
                filename = os.path.join(root, f)
                filename = os.path.abspath(filename)
                if _FILENAME_PATTERN.match(filename) is not None:
                    result.append(filename)
        return result


async def watcher() -> None:
    async for event in watchfiles.awatch(WATCH_DIRECTORY, force_polling=True, watch_filter=file_filter):
        logger.debug(event)
        for _, filename in tuple(event):
            logger.debug(filename)
            device = devices()[os.path.abspath(filename)]
            logger.debug(f"{device}, {device._state}")
            new = await device.read()
            logger.debug(f"{device} - {new} - {device._state}")


class Device:
    PAYLOAD_ON = "1"
    PAYLOAD_OFF = "0"

    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._state = False
        self._state_lock = asyncio.Lock()
        self._file_handle = None

    def __repr__(self) -> str:
        return f"<Device {self._filename} - {self._state}>"

    async def _get_file_handle(self) -> AsyncTextIOWrapper:
        if self._file_handle is None:
            self._file_handle = await aiofiles.open(self._filename, "w+")
        return self._file_handle

    async def read(self) -> bool:
        logger.debug("reading")
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            data = await fh.read(1)
            logger.debug(data)
            match data:
                case Device.PAYLOAD_ON:
                    self._state = True
                case Device.PAYLOAD_OFF:
                    self._state = False
                case _:
                    logger.warning("Could not match state: %s", data)
            return self._state

    async def write(self, state: bool) -> None:
        payload = Device.PAYLOAD_ON if state else Device.PAYLOAD_OFF
        logger.debug(payload)
        async with self._state_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            await fh.write(payload)
        await self.read()
        logger.debug("finished writing state %s", state)


_DEVICES: typing.Dict[str, Device] = {}


def devices() -> typing.Dict[str, Device]:
    global _DEVICES
    if not _DEVICES:
        _DEVICES = {filename: Device(filename) for filename in crawl(WATCH_DIRECTORY)}
    return _DEVICES


async def backgroundwriter(device) -> None:
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to true")
    await device.write(True)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to false")
    await device.write(False)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to true")
    await device.write(True)


async def main() -> None:
    jobs = []
    # filenames = crawl(WATCH_DIRECTORY)
    # for filename in filenames:
    #     device = devices()[filename]
    #     jobs += [backgroundwriter(device)]
    jobs.append(watcher())
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
