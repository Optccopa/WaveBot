import asyncio, logging

log = logging.getLogger(__name__)


async def retry_with_backoff(coro, retries: int = 5):
    delay = 1
    for _ in range(retries):
        try:
            return await coro()
        except Exception as e:
            log.warning("Retry in %ds: %s", delay, e)
            await asyncio.sleep(delay)
            delay *= 2
    raise RuntimeError("Max retries exceeded")
