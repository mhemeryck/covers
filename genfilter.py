import asyncio
import typing


async def gen() -> typing.AsyncGenerator[int, None]:
    count = 0
    while True:
        count = (count + 1) % 10
        await asyncio.sleep(1)
        yield count


async def odd(g: typing.AsyncGenerator[int, None]) -> typing.AsyncGenerator[int, None]:
    async for el in g:
        if el % 2 == 1:
            yield el


async def even(g: typing.AsyncGenerator[int, None]) -> typing.AsyncGenerator[int, None]:
    async for el in g:
        if el % 2 == 0:
            yield el


async def print_loop(name: str, g: typing.AsyncGenerator[int, None]) -> None:
    async for el in g:
        print(f"{name} - {el}")


async def main():
    g = gen()
    await asyncio.gather(
        *(
            print_loop("original", g),
            print_loop("odd", odd(g)),
            print_loop("even", even(g)),
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
