# WaveBot Codebase Review

---

## 1. Issues & Bugs

### `owneronly.py:29-56` — Unvalidated `int()` conversion
`int(guild_id)` is called without a try/except. Any non-numeric input raises `ValueError` and crashes the interaction.

### `config.py:60-66` — `None.mention` crash
If `log_channel` is not configured or the channel was deleted, `channel` is `None` and `channel.mention` throws `AttributeError`.
```python
channel = interaction.guild.get_channel(config.get('log_channel'))
# ... no None check
await interaction.response.send_message(f"... Watch {channel.mention} ...")
```

### `partner.py:243-245` — TOCTOU race condition in cooldown lock
`exists()` check and `set()` are two separate operations. With multiple shards, both can read `False` before either sets the key, triggering duplicate partner runs.
```python
if await self.redis.exists("last_partner_run"):
    return
await self.redis.set("last_partner_run", 1, ex=10800)
```
Fix: Use atomic `SET NX`:
```python
if not await self.redis.set("last_partner_run", 1, ex=10800, nx=True):
    return
```

### `cache_ads.py:143-150` — Silent failure defaults to unsafe
When Claude's response isn't valid JSON, the fallback is `sus=False` — ads pass through instead of being held for review. The failure isn't logged with context either.
```python
except json.JSONDecodeError:
    print(f"Failed to parse claude haiku response")
    result = {"sus": False, "confidence": 0.0, ...}
```

### `partner.py:19` — Hardcoded bot client ID in OAuth URL
```python
value='[Click Here](https://discord.com/oauth2/authorize?client_id=1487962334138863666)'
```
Fix: `client_id={self.bot.user.id}`

### `tests/claude.py:4` — Broken import
```python
from src.prompts import *
```
`src/prompts.py` does not exist. This test file cannot run.

### `main.py:93` — Typo
`"Failed starting on all trys"` → `"tries"`

---

## 2. Security Concerns

### `.env` — Real credentials committed to repo (CRITICAL)
A Discord bot token and Anthropic API key are stored in plaintext in `.env`. If this repo is or has ever been public, both must be rotated immediately. `.env` should be in `.gitignore` and removed from git history (`git filter-branch` or `git-filter-repo`).

### `tests/claude.py:6` — API key hardcoded in test file (CRITICAL)
Same Anthropic API key from `.env` is hardcoded in a test file. Tests must never contain real credentials.

### `docker/docker-compose.yaml:14` — Hardcoded DB password
```yaml
POSTGRES_PASSWORD: SuperSecretPass1235
```
Should be `${POSTGRES_PASSWORD}` pulled from a separate secrets file.

### `configmanager.py:30-44` — Column name injection risk
Column names from `**fields` are interpolated directly into the SQL string, not parameterized. asyncpg prevents value injection but column names are unrestricted. Needs an explicit allowlist:
```python
ALLOWED_FIELDS = {"partner_channel", "ad_channel", "log_channel", ...}
for k in fields:
    if k not in ALLOWED_FIELDS:
        raise ValueError(f"Unknown field: {k}")
```

### `owneronly.py` — No validation of reason/text fields
`reason` in blacklist/whitelist commands is stored directly without sanitization. Low risk given owner-only gate, but worth noting.

---

## 3. Performance

### `partner.py:251-270` — N+1 Redis/DB queries in partner loop
Each guild triggers an individual `config.get(guild.id)` call. With 100 guilds, that's 100 serial lookups. Batch with `MGET`:
```python
keys = [f"config:{g.id}" for g in self.bot.guilds]
results = await self.redis.mget(keys)
```

### `cache_ads.py:199` — Blocking Anthropic call in thread pool
`scan_ad()` is synchronous and uses the blocking `anthropic` client. Running it via `run_in_executor` occupies one thread per guild for the duration of the API call (1–5s). With many guilds, this exhausts the thread pool.
Fix: Use `anthropic.AsyncAnthropic` and `await` natively.

### `cache_ads.py:129-142` — No timeout on Anthropic API calls
If the API hangs, the executor thread blocks indefinitely. Wrap with `asyncio.wait_for(..., timeout=30.0)`.

### `partner.py:111-131` — O(n²) match_servers algorithm
For each server, scans the entire remaining pool for candidates. Use an indexed approach or random pairing from a shuffled list in a single pass.

### `cache_ads.py:174` — Unbounded Redis pipeline
All guilds are queued into one pipeline before execute. At scale (10k+ guilds) this creates a large memory spike and a massive single transaction. Chunk into batches of ~500.

### `main.py:39-62` — Missing indexes on frequently queried columns
`blacklists.guild_id` and `whitelisted_links.link` are queried on every check but have no index beyond the PK on `guild_config`.
```sql
CREATE INDEX IF NOT EXISTS idx_blacklists_guild_id ON blacklists(guild_id);
CREATE INDEX IF NOT EXISTS idx_whitelisted_links_link ON whitelisted_links(link);
```

---

## 4. Code Quality

### `owneronly.py:161-312` — `debug_server` and `debug_all_servers` duplicate ~80 lines
Both functions build the same embed with the same channel/role resolution logic. Extract into `_build_debug_embed(guild)`.

### Entire codebase — `print()` used everywhere instead of `logging`
```python
print(f"Failed to load {ext}: {e}")   # main.py:72
print(response)                        # cache_ads.py:204
print(e)                               # partner.py:219
```
No log levels, no rotation, no persistence. Replace with Python `logging`:
```python
import logging
logger = logging.getLogger(__name__)
logger.error("Failed to load %s", ext, exc_info=True)
```

### `partner.py:216-225` — Bare `except Exception` swallows all errors
Discord-specific errors (`Forbidden`, `HTTPException`) should be caught and handled distinctly. Silent `print(e)` + return means partnership failures go completely unnoticed.

### `owneronly.py:138+` — Emoji strings render as literal text
```python
':green_circle:'  →  appears as `:green_circle:` in Discord, not 🟢
```
Use Unicode: `'🟢'` / `'🔴'`

### `tests/` — Three separate scan implementations with diverging regex patterns
`tests/claude.py`, `tests/scanfuncs.py`, `tests/scan_ads(3).py`, and `cogs/cache_ads.py` all define ad-detection logic independently. The regex patterns differ across files (e.g., `\b/inv\b` and PayPal checks are missing from some). The missing `src/prompts.py` was clearly intended to be the shared source of truth.

### `main.py:102-105` — `close()` doesn't guard against partial failures
If Redis `aclose()` throws after DB pool has already closed, the exception propagates and `super().close()` is never called. Wrap each in a try/except.

### `cache_ads.py` — MD5 used for ad deduplication hashing
`hashlib.md5(...)` — not a security issue in this context, but SHA-256 is trivially better and avoids a code review flag in any future security audit.

---

## 5. Missing Features

### `src/prompts.py` — Referenced but doesn't exist
`tests/claude.py` imports `RULE_PATTERNS` and `SCAN_PROMPT` from this module. The file was likely planned as a shared prompts/patterns module but was never created. The patterns live only in `cache_ads.py`.

### No database migration system
Schema is created inline at bot startup via `CREATE TABLE IF NOT EXISTS`. There's no versioning, no rollback, and no safe path for schema changes in production. Alembic or a simple versioned SQL file approach is needed.

### No structured logging / monitoring
No metrics on ad scan pass/fail rates, partner success rates, API latency, Redis hit/miss, or DB pool exhaustion. No alerting if the ad loop starts silently failing.

### No rate limiting on Anthropic API calls
`ad_loop` fires for all guilds every 3 hours simultaneously with no concurrency control. At scale this will hit API rate limits with no retry/backoff logic.

### `cache_ads.py` — No handling when Claude structured output is malformed
The JSON parsing `"{" + message.content[0].text.strip()` is brittle. If Claude returns anything that isn't a partial JSON object starting after `{`, parsing fails. Structured outputs (via `response_format`) would be more robust.

---

## 6. Suggestions

### Use `asyncpg` connection pool sizing explicitly
`main.py` creates the pool without `min_size`/`max_size`. Under load (partner loop + ad loop running simultaneously), the pool can either over-provision or queue unnecessarily.

### Add a startup health check
Before the bot connects to Discord, verify Redis and Postgres are reachable. Currently a misconfigured Redis URL results in a cryptic runtime error the first time a command is used.

### Move ad regex patterns to config or a shared module
Patterns change frequently (new scam vectors). Centralizing them in `src/prompts.py` (the intended design) makes updates safe without touching cog logic.

### Use `discord.app_commands.checks.bot_has_permissions()` decorators
Rather than catching `Forbidden` at send time, declare required permissions upfront. Gives users clearer setup errors.

### `partner.py` match pairing — consider weight by member count similarity
Currently fully random. Pairing servers by similar member counts improves partnership quality and reduces complaints from large servers being paired with tiny ones.

### Consider caching blacklist/whitelist lookups in Redis
Both are checked per event but only change via explicit owner commands. A short TTL Redis cache (5 min) would avoid repeated DB hits. The pattern is already established in `configmanager.py`.

---

## 7. Summary

**Overall health: 5/10**

The core logic works and the Redis-first architecture is sensible, but the codebase has critical security issues that need immediate action and several reliability gaps that will surface as the bot scales.

### Top 3 things to fix first

1. **Rotate and remove the committed credentials** — The Discord token and Anthropic API key in `.env` and `tests/claude.py` are the only thing on this list that can cause immediate, irreversible damage (bot hijack, API billing abuse). Do this before anything else.

2. **Fix the `config.py` None crash and the `owneronly.py` type bug** — Both are user-facing crashes in common flows. The `channel.mention` on a None object will break the setup command for any guild that hasn't configured a log channel, which is likely most new guilds.

3. **Replace the TOCTOU Redis lock in `partner.py`** with an atomic `SET NX` — The partner loop is the bot's core feature. Duplicate runs cause duplicate ad posts to both servers in a pair, which directly damages the user experience and trust in the bot.
