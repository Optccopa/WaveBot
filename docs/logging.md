# Logging

## Log Levels

- `DEBUG` — verbose: cooldown key hits, member counts, ad lengths, guild resolution
- `INFO` — normal operations: loop ticks, eligible guilds, matched pairs, sent ads
- `WARNING` — skipped guilds (missing config, sat out), failed sends, `discord.Forbidden` from bot permission errors in commands
- `ERROR` — exceptions: failed extension loads, Claude parse failures, send failures

`discord` and `discord.http` loggers are set to `WARNING` to suppress library noise.

## Console / File

Standard `logging.basicConfig` to stdout. Format: `HH:MM:SS [LEVEL] logger.name: message`.

## Webhook Handler

`WebhookHandler` in `main.py` sends all `DEBUG`+ log records to a Discord webhook configured via `LOG_WEBHOOK_URL` env var. If not set, no webhook handler is added.

### Queue Design

Records go into an `asyncio.Queue(maxsize=500)`. When full, new records are silently dropped (`put_nowait` with no exception re-raise). A background worker task drains the queue and posts to the webhook.

### Batching

Worker waits for the first record, sleeps 2 seconds, then drains everything currently in the queue into a batch. All records in the batch are packed into embed fields and sent together, reducing webhook traffic and latency.

Limits respected per batch:
- `FIELD_MAX = 25` fields per embed
- `EMBED_CHARS = 5800` characters per embed (safe under Discord's 6000 limit)
- `VALUE_MAX = 1014` characters per field value (1024 − 8 for triple-backtick fences − 2 safety margin)
- Up to 10 embeds per webhook message (Discord limit)

Each log entry becomes one embed field (`name: \u200b`, `value: ```\n{entry}\n````, `inline: false`). When an embed would exceed field count or char budget, a new embed is started. Messages are sent in groups of 10 embeds.

### Retry Logic

Each webhook POST gets 3 attempts:
- On 429: reads `retry_after` from Discord JSON, sleeps that duration, logs to stderr, retries
- On HTTP 4xx/5xx (non-429): logs status + attempt number to stderr, sleeps 1s, retries
- On exception: logs exception message + attempt number to stderr, sleeps 1s, retries
- After 3 failures: logs drop notice to stderr (embed count dropped)

Cannot use the normal logger for retry errors — it would recurse back into the webhook handler. All retry/failure output goes to `sys.stderr`.

`task_done()` is called for every record in the batch inside a `finally` block, regardless of send success or failure.

### Graceful Shutdown

`close_async()` is called in `Bot.close()`:
1. `await self._queue.join()` — drains all pending records
2. `self._task.cancel()` + `await self._task` (catching `CancelledError`) — stops the worker
3. `await self.session.close()` — closes the aiohttp session

## Error Handler (`cogs/errorhandler.py`)

Handles both prefix (`on_command_error`) and slash (`on_app_command_error`) errors.

- `MissingPermissions` / `CommandOnCooldown` — user-facing message only, not stored in `last_errors`
- `discord.Forbidden` — logged at `WARNING`, hint message sent to user, not stored in `last_errors`
- All other errors — logged at `ERROR`, stored in `last_errors`, retrievable via `/error` (owner only)

### Cooldown dedup

Prefix `CommandOnCooldown` sends one message per cooldown window. The user is added to a module-level set on first hit; subsequent triggers are silently dropped until `retry_after` seconds elapse.

## Guild Log Channel

Each guild optionally configures a `log_channel`. The bot sends embeds here when:
- Partner channel is the wrong type
- Bot is missing permissions in partner channel
- Guild fails `validate_server`
- Ad channel not found (during ad scanning loop)
- Ad message not found in ad channel

These are fire-and-forget — failures are silently caught with `except discord.Forbidden: pass`.
