import asyncio
import logging
import os
import typing

import aiofiles
from aiofiles.threadpool.text import AsyncTextIOWrapper

FILENAME: str = "relay_state"
INTERVAL = 0.100

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.DEBUG,
)
logger = logging.getLogger(__name__)


_file_handle_q_type = asyncio.Queue[typing.Tuple[str, AsyncTextIOWrapper]]
_event_q_type = asyncio.Queue[typing.Tuple[str, str]]


async def worker(file_handle_q: _file_handle_q_type, event_q: _event_q_type) -> None:
    fid, fh = await file_handle_q.get()
    try:
        await fh.seek(0)
        data = await fh.read()
    finally:
        file_handle_q.task_done()
    await event_q.put((fid, data))


class FileMonitor:
    def __init__(
        self,
        filename: str,
        file_handle_q: _file_handle_q_type,
        event_q: _event_q_type,
    ) -> None:
        self._id = filename
        self._filename = filename
        self._state = False
        self._previous = False
        self._file_lock = asyncio.Lock()
        self._file_handle = None
        self._file_handle_q = file_handle_q
        self._event_q = event_q

    async def _get_file_handle(self) -> AsyncTextIOWrapper:
        if self._file_handle is None:
            self._file_handle = await aiofiles.open(self._filename, "r+")
        return self._file_handle

    async def poll(self, interval: float = INTERVAL) -> None:
        """Poll produces polling jobs"""
        while True:
            async with self._file_lock:
                fh = await self._get_file_handle()
                await self._file_handle_q.put((self._id, fh))
            await asyncio.sleep(interval)

    async def read(self, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
        """read consumes events coming back from the polling jobs"""
        while True:
            # async with self._file_lock:
            #     fh = await self._get_file_handle()
            #     await fh.seek(0)
            #     new = await fh.read()
            (fid, new) = await self._event_q.get()
            # Ignore events which aren't ours
            if fid != self._id:
                continue
            self._event_q.task_done()

            match new:
                case "1\n":
                    self._state = True
                case "0\n":
                    self._state = False
                case _:
                    logger.debug(f"something went wrong, state: {new}")
                    pass

            if self._state != self._previous:
                logger.debug(f"Found something new {self._previous} -> {self._state}")
                self._previous = self._state
                yield self._state
            await asyncio.sleep(interval)

    async def write(self, state: bool) -> int:
        logger.debug("trigger write")
        data = "1\n" if state else "0\n"
        async with self._file_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            n = await fh.write(data)
            await fh.flush()
        return n


async def main() -> None:
    paths = []
    for root, _, files in os.walk("./fixtures"):
        for f in files:
            if "relay_state_" in f:
                paths.append(os.path.join(root, f))

    monitors = [FileMonitor(p) for p in paths]
    # fm = FileMonitor(FILENAME)

    # async def reader():
    #     async for event in fm.read():
    #         logger.debug(f"Read an event: {event}")

    # async def writer():
    #     await asyncio.sleep(2)
    #     await fm.write(True)
    #     await asyncio.sleep(2)
    #     await fm.write(False)
    #     await asyncio.sleep(2)

    # await asyncio.gather(reader(), writer())

    async def reader(monitor: FileMonitor) -> None:
        async for event in monitor.read():
            logger.debug(f"Read event for monitor {monitor._filename}: {event}")

    await asyncio.gather(*[reader(monitor) for monitor in monitors])


if __name__ == "__main__":
    asyncio.run(main())
