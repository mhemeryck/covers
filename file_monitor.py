import asyncio
import os
import threading

from watchdog.observers.polling import PollingObserverVFS
from watchdog.events import FileSystemEventHandler

queue = asyncio.Queue()


# Define an async function to handle file system events
async def handle_event(event):
    # print(f"Event type: {event.event_type} - Path: {event.src_path}")
    # Simulate an async operation
    await queue.put(str(event))


# Create a custom event handler that triggers the async function
class AsyncEventHandler(FileSystemEventHandler):
    def __init__(self, loop):
        self.loop = loop

    def on_modified(self, event):
        self.loop.call_soon_threadsafe(asyncio.create_task, handle_event(event))

    def on_created(self, event):
        self.loop.call_soon_threadsafe(asyncio.create_task, handle_event(event))


def start_watchdog(path, event_handler):
    observer = PollingObserverVFS(stat=os.stat, listdir=os.scandir, polling_interval=0.10)
    observer.schedule(event_handler, path, recursive=True)
    observer.start()
    observer.join()


async def worker(queue) -> None:
    while True:
        event = await queue.get()
        print(f"worker {event}")
        queue.task_done()


async def main():
    path = "./fixtures"  # Replace with the path you want to monitor

    loop = asyncio.get_running_loop()
    event_handler = AsyncEventHandler(loop)

    watchdog_thread = threading.Thread(target=start_watchdog, args=(path, event_handler))
    watchdog_thread.daemon = True  # Allow thread to exit when main program exits
    watchdog_thread.start()

    task = loop.create_task(worker(queue))
    await task

    # try:
    #     while True:
    #         await asyncio.sleep(1)
    # except asyncio.CancelledError:
    #     pass
    # finally:
    #     print("Stopping observer")
    # observer.stop()
    # observer.join()


if __name__ == "__main__":
    asyncio.run(main())
