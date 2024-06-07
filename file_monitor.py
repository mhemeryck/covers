import asyncio
import watchfiles

WATCH_DIRECTORY = "./fixtures"


async def watch(watch_dir):
    async for event in watchfiles.awatch(watch_dir, force_polling=True):
        print(event)


if __name__ == "__main__":
    asyncio.run(watch(WATCH_DIRECTORY))
