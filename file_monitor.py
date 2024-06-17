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


def device_filter(change: watchfiles.Change, path: str) -> bool:
    return change == watchfiles.Change.modified and any(
        path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
    )


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
            await fh.writelines([payload])
            await fh.flush()
        await self.read()
        logger.debug("finished writing state %s", state)


class Unispy:
    """Unispy watches a unipi for changes and pushes out events"""

    def __init__(self, folder: str) -> None:
        self._folder = folder
        self._devices_for_filename, self._devices_for_device_name = self._crawl(folder)

    def _crawl(self, folder: str) -> typing.Tuple[typing.Dict[str, Device], typing.Dict[str, Device]]:
        for_filename = {}
        for_device_name = {}
        for root, _, files in os.walk(folder):
            for f in files:
                filename = os.path.join(root, f)
                if (match := _FILENAME_PATTERN.match(filename)) and match is not None:
                    full_path = os.path.abspath(filename)
                    device_name = "{device_fmt}_{io_group}_{number}".format(**match.groupdict())
                    for_filename[full_path] = for_device_name[device_name] = Device(full_path)
        logger.debug(for_device_name)
        return for_filename, for_device_name

    async def read(self) -> None:
        async for event in watchfiles.awatch(self._folder, force_polling=True, watch_filter=device_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                logger.debug(filename)
                device = self._devices_for_filename[os.path.abspath(filename)]
                logger.debug(f"{device}, {device._state}")
                new = await device.read()
                logger.debug(f"{device} - {new} - {device._state}")

    async def write(self, device_name: str, state: bool) -> None:
        """Update device with name to state"""
        await self._devices_for_device_name[device_name].write(state)


async def backgroundwriter(spy: Unispy) -> None:
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to true")
    await spy.write("di_1_03", True)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to false")
    await spy.write("di_1_03", False)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    # logger.debug("trigger to true")
    # await spy.write("di_1_03", True)


async def main() -> None:
    spy = Unispy(WATCH_DIRECTORY)
    jobs = []
    jobs.append(backgroundwriter(spy))
    jobs.append(spy.read())
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
