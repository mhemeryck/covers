import asyncio
import os
import sys
import logging

from watchdog.observers.polling import PollingObserverVFS
from watchdog.events import FileSystemEventHandler

# LOOP = asyncio.new_event_loop()


async def worker(queue: asyncio.Queue[str]) -> None:
    while True:
        event = await queue.get()
        print(f"worker received: {event}")
        queue.task_done()


class EventHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue[str]) -> None:
        self._queue = queue

    def dispatch(self, event):
        # asyncio.get_running_loop().run_until_complete(self.)
        # wrap in async context
        # asyncio.create_task(self._queue.put(str(event)))
        print("dispatch")
        # self._loop.create_task(self.put(str(event)))
        asyncio.run(self.put(str(event)))
        # LOOP.run_until_complete(self.put(str(event)))

    async def put(self, event: str) -> None:
        print(event)
        await self._queue.put(event)


async def file_watcher(queue: asyncio.Queue) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    path = sys.argv[1] if len(sys.argv) > 1 else "."
    event_handler = EventHandler(queue)
    observer = PollingObserverVFS(stat=os.stat, listdir=os.scandir, polling_interval=0.10)
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    try:
        while observer.is_alive():
            observer.join(1)
    finally:
        observer.stop()
        observer.join()


async def main() -> None:
    queue = asyncio.Queue()
    await asyncio.gather(
        *[
            file_watcher(queue),
            worker(queue),
        ]
    )


if __name__ == "__main__":
    asyncio.run(main())
    # LOOP.run_until_complete(main())
