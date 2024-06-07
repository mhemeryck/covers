import asyncio
import os

# from hachiko.hachiko import AIOWatchdog
from watchdog.observers.polling import PollingObserverVFS

WATCH_DIRECTORY = "./fixtures"


class EventHandler:
    def __init__(self, queue: asyncio.Queue):
        self._loop = asyncio.get_event_loop()
        self._queue = queue

    async def handler(self, event):
        await self._queue.put(event)
        print(f"handle event async: {event}")

    def dispatch(self, event):
        # print(event)
        self._loop.call_soon_threadsafe(asyncio.create_task, self.handler(event))


async def worker(queue: asyncio.Queue) -> None:
    while True:
        event = await queue.get()
        print(f"received event from queue: {event}")
        queue.task_done()


async def watch_fs(watch_dir):
    queue = asyncio.Queue()
    observer = PollingObserverVFS(stat=os.stat, listdir=os.scandir, polling_interval=0.1)
    event_handler = EventHandler(queue)
    observer.schedule(event_handler, watch_dir, True)
    observer.start()

    # watch = AIOWatchdog(watch_dir, event_handler=EventHandler(queue=queue), observer=observer)
    # watch.start()

    await worker(queue)
    # for _ in range(20):
    #     await asyncio.sleep(1)
    observer.stop()
    observer.join()
    # watch.stop()


# asyncio.get_event_loop().run_until_complete(watch_fs(WATCH_DIRECTORY))
if __name__ == "__main__":
    asyncio.run(watch_fs(WATCH_DIRECTORY))
