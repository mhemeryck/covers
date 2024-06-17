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


class Watcher:
    def __init__(self, folder: str) -> None:
        self._folder = folder
        self._devices_for_filename = self._find_devices_by_filename(folder)
        self._device_for_name: typing.Dict[str, Device] = {}

    def _crawl(self, folder: str) -> typing.List[typing.Tuple[str, str]]:
        result = []
        for root, _, files in os.walk(folder):
            for f in files:
                filename = os.path.join(root, f)
                filename = os.path.abspath(filename)
                if match := _FILENAME_PATTERN.match(filename) and match is not None:
                    device_name = "{device_fmt}_{io_group}_{number}".format(**match.groupdict())
                    result.append((device_name, filename))
        return result

    def _find_devices_by_filename(self, folder: str) -> typing.Dict[str, Device]:
        "Create initial mapping filename to Device entry"
        return {filename: Device(filename) for _, filename in self._crawl(folder)}

    def _find_devices_by_name(self, device_name: str) -> Device:
        # TODO: fixme
        return self._device_for_name[device_name]

    def _device_for_filename(self, filename: str) -> Device:
        return self._devices_for_filename[os.path.abspath(filename)]

    async def read(self) -> None:
        async for event in watchfiles.awatch(self._folder, force_polling=True, watch_filter=device_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                logger.debug(filename)
                device = self._device_for_filename(filename)
                logger.debug(f"{device}, {device._state}")
                new = await device.read()
                logger.debug(f"{device} - {new} - {device._state}")

    async def write(self, device_name: str, state: bool) -> None:
        """Update device with name to state"""
        await self._device_for_name[device_name].write(state)


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
    watcher = Watcher(WATCH_DIRECTORY)
    jobs = []
    # filenames = crawl(WATCH_DIRECTORY)
    # for filename in filenames:
    #     device = devices()[filename]
    #     jobs += [backgroundwriter(device)]
    jobs.append(watcher.read())
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
