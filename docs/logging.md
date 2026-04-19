# Logging

## Log Levels

- `DEBUG` — verbose: cooldown key hits, member counts, ad lengths, guild resolution
- `INFO` — normal operations: loop ticks, eligible guilds, matched pairs, sent ads
- `WARNING` — skipped guilds (missing config, sat out), failed sends
- `ERROR` — exceptions: failed extension loads, Claude parse failures, send failures

`discord` and `discord.http` loggers are set to `WARNING` to suppress library noise.

## Console / File

Standard `logging.basicConfig` to stdout. Format: `HH:MM:SS [LEVEL] logger.name: message`.

## Webhook Handler

`WebhookHandler` in `main.py` sends all `DEBUG`+ log records to a Discord webhook configured via `LOG_WEBHOOK_URL` env var. If not set, no webhook handler is added.

### Queue Design

Records go into an `asyncio.Queue(maxsize=500)`. When full, new records are silently dropped (`put_nowait` with no exception re-raise). A background worker task drains the queue and posts to the webhook.

### Retry Logic

Each message gets 3 attempts:
- On 429: reads `retry_after` from Discord's JSON response and sleeps that duration before retrying
- On other exception: sleeps 1 second before retrying
- After 3 failures: drops the message and marks the queue task done

### Graceful Shutdown

`close_async()` is called in `Bot.close()`:
1. `await self._queue.join()` — drains all pending records
2. `self._task.cancel()` + `await self._task` (catching `CancelledError`) — stops the worker
3. `await self.session.close()` — closes the aiohttp session

### Truncation

Messages are truncated to 1990 characters and wrapped in a code block before posting. Discord's message limit is 2000 chars; the 10-char buffer covers the ` ``` ` fences.

## Guild Log Channel

Each guild optionally configures a `log_channel`. The bot sends embeds here when:
- Partner channel is the wrong type
- Bot is missing permissions in partner channel
- Guild fails `validate_server`
- Ad channel not found (during ad scanning loop)
- Ad message not found in ad channel

These are fire-and-forget — failures are silently caught with `except discord.Forbidden: pass`.
