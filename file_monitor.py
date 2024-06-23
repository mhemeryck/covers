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
    format="%(asctime)s [%(levelname)s - %(funcName)s] %(message)s",
)


def device_filter(change: watchfiles.Change, path: str) -> bool:
    return change == watchfiles.Change.modified and any(
        path.endswith(f"{ending}_value") for ending in ("di", "do", "ro")
    )


class IO:
    PAYLOAD_ON = "1"
    PAYLOAD_OFF = "0"

    def __init__(self, filename: str) -> None:
        self._filename = filename
        self._state = False
        self._state_lock = asyncio.Lock()
        self._read_file_handle = None
        self._write_file_handle = None

    def __repr__(self) -> str:
        return f"<Device {self._filename} - {self._state}>"

    async def _get_write_file_handle(self) -> AsyncTextIOWrapper:
        if self._write_file_handle is None:
            self._write_file_handle = await aiofiles.open(self._filename, "w")
        return self._write_file_handle

    async def _get_read_file_handle(self) -> AsyncTextIOWrapper:
        if self._read_file_handle is None:
            self._read_file_handle = await aiofiles.open(self._filename, "r")
        return self._read_file_handle

    async def read(self) -> bool:
        async with self._state_lock:
            logger.debug("reading %s", self)
            fh = await self._get_read_file_handle()
            await fh.seek(0)
            data = await fh.read(1)
            logger.debug(data)
            match data:
                case IO.PAYLOAD_ON:
                    self._state = True
                case IO.PAYLOAD_OFF:
                    self._state = False
                case _:
                    logger.warning("Could not match state: %s", data)
            return self._state

    async def write(self, state: bool) -> None:
        payload = IO.PAYLOAD_ON if state else IO.PAYLOAD_OFF
        logger.debug(payload)
        async with self._state_lock:
            logger.debug("writing %s", self)
            fh = await self._get_write_file_handle()
            await fh.seek(0)
            await fh.write(f"{payload}\n")
            # await fh.writelines([payload])
            await fh.flush()
        # logger.debug("finished writing state %s", state)


EventType = typing.Tuple[IO, bool]


class Unispy:
    """Unispy watches a unipi for changes and pushes out events"""

    def __init__(self, folder: str) -> None:
        self._folder = folder
        self._devices_for_filename, self._devices_for_device_name = self._crawl(folder)

    def _crawl(self, folder: str) -> typing.Tuple[typing.Dict[str, IO], typing.Dict[str, IO]]:
        for_filename = {}
        for_device_name = {}
        for root, _, files in os.walk(folder):
            for f in files:
                filename = os.path.join(root, f)
                if (match := _FILENAME_PATTERN.match(filename)) and match is not None:
                    full_path = os.path.abspath(filename)
                    device_name = "{device_fmt}_{io_group}_{number}".format(**match.groupdict())
                    for_filename[full_path] = for_device_name[device_name] = IO(full_path)
        return for_filename, for_device_name

    async def read(self) -> typing.AsyncGenerator[EventType, None]:
        async for event in watchfiles.awatch(self._folder, force_polling=True, watch_filter=device_filter):
            logger.debug(event)
            for _, filename in tuple(event):
                # logger.debug(filename)
                device = self._devices_for_filename[os.path.abspath(filename)]
                # logger.debug(device)
                state = await device.read()
                # logger.debug(device)
                yield (device, state)

    async def write(self, device_name: str, state: bool) -> None:
        """Update device with name to state"""
        await self._devices_for_device_name[device_name].write(state)


async def backgroundwriter(spy: Unispy, device_name: str) -> None:
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to true")
    await spy.write(device_name, False)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    logger.debug("trigger to false")
    await spy.write(device_name, True)
    logger.debug("sleeping")
    await asyncio.sleep(2)
    # logger.debug("trigger to true")
    # await spy.write("di_1_03", True)


async def backgroundreader(spy: Unispy) -> None:
    async for device, state in spy.read():
        logger.debug("background reader got %s - %s", device, state)


class Device:
    """Manages a single unipi device"""

    def __init__(self) -> None:
        self._spy = Unispy(WATCH_DIRECTORY)

    async def _read_file_watcher(self) -> None:
        async for device, state in self._spy.read():
            logger.debug("background reader got %s - %s", device, state)

    async def run(self) -> None:
        """Run main event loop"""
        await self._read_file_watcher()


class PushButton:
    """Contains the data for a push button"""

    def __init__(self, identifier: str, state: bool) -> None:
        self._identifier = identifier
        self._state = state

    def write(self, state: bool) -> None:
        self._state = state


class Light:
    """Contains the data for a light"""


async def main() -> None:
    # spy = Unispy(WATCH_DIRECTORY)
    # jobs = []
    # for n in range(1, 13):
    #     device_name = f"ro_2_{n:02d}"
    #     jobs.append(backgroundwriter(spy, device_name))
    # jobs.append(backgroundreader(spy))
    # # jobs.append(spy.read())
    # await asyncio.gather(*jobs)
    device = Device()
    await device.run()


if __name__ == "__main__":
    asyncio.run(main())
