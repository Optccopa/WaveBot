import asyncio

async def retry_with_backoff(coro, retries: int = 5):
    delay = 1
    for _ in range(retries):
        try:
            return await coro()
        except Exception as e:
            print(f"Retry in {delay}s: {e}")
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("Max retries exceeded")