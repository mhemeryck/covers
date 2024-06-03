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
    logger.debug("start worker")
    while True:
        fid, fh = await file_handle_q.get()
        try:
            await fh.seek(0)
            data = await fh.read()
            # if fid.endswith("relay_state_1"):
            #     logger.debug(f"worker checking {fid} - {data}")
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

    async def submit(self, interval: float = INTERVAL) -> None:
        """Poll produces polling jobs"""
        while True:
            async with self._file_lock:
                fh = await self._get_file_handle()
                await self._file_handle_q.put((self._id, fh))
            await asyncio.sleep(interval)

    # async def poll(self, interval: float = INTERVAL) -> typing.AsyncGenerator[bool, None]:
    #     """read consumes events coming back from the polling jobs"""
    #     while True:
    #         # async with self._file_lock:
    #         #     fh = await self._get_file_handle()
    #         #     await fh.seek(0)
    #         #     new = await fh.read()
    #         (fid, new) = await self._event_q.get()
    #         # Ignore events which aren't ours
    #         if fid != self._id:
    #             logger.debug(f"mismatching id {fid} != {self._id}")
    #             continue
    #         self._event_q.task_done()

    #         match new:
    #             case "1\n":
    #                 self._state = True
    #             case "0\n":
    #                 self._state = False
    #             case _:
    #                 logger.debug(f"something went wrong, state: {new}")
    #                 pass

    #         if self._state != self._previous:
    #             logger.debug(f"Found something new {self._previous} -> {self._state}")
    #             self._previous = self._state
    #             yield self._state
    #         await asyncio.sleep(interval)

    async def write(self, state: bool) -> int:
        logger.debug("trigger write")
        data = "1\n" if state else "0\n"
        async with self._file_lock:
            fh = await self._get_file_handle()
            await fh.seek(0)
            n = await fh.write(data)
            await fh.flush()
        return n


async def process(queue: _event_q_type) -> typing.AsyncGenerator[bool, None]:
    states: typing.Dict[str, bool] = {}
    while True:
        (fid, new) = await queue.get()
        queue.task_done()

        if fid.endswith("relay_state_1"):
            logger.debug(f"{fid} - {new}")

        yield new == "1\n"

        # match new:
        #     case "1\n":
        #         state = True
        #     case "0\n":
        #         state = False
        #     case _:
        #         logger.debug(f"something went wrong, state: {new}")
        #         pass

        # try:
        #     previous = states[fid]
        # except KeyError:
        #     states[fid] = previous = not state

        # if state != previous:
        #     logger.debug(f"Found something new {fid}: {previous} -> {state}")
        #     states[fid] = state
        #     yield state
        await asyncio.sleep(INTERVAL)


async def main() -> None:
    paths = []
    for root, _, files in os.walk("./fixtures"):
        for f in files:
            if "relay_state_" in f:
                paths.append(os.path.join(root, f))

    file_handle_q = asyncio.Queue()
    event_q = asyncio.Queue()

    monitors = [FileMonitor(p, file_handle_q, event_q) for p in paths]

    # async def reader(monitor: FileMonitor) -> None:
    #     async for event in monitor.poll():
    #         logger.debug(f"Read event for monitor {monitor._filename}: {event}")
    async def reader() -> None:
        logger.debug("process")
        async for event in process(event_q):
            logger.debug(f"process: {event}")

    producers = [monitor.submit() for monitor in monitors]
    # producers += [reader()]
    workers = [worker(file_handle_q, event_q) for _ in range(10)]
    jobs = producers + workers + [reader()]
    await asyncio.gather(*jobs)


if __name__ == "__main__":
    asyncio.run(main())
