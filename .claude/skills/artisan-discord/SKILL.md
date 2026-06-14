# WaveBot — Discord Bot Development Skill

Production patterns for this specific codebase. Sourced from existing cogs, not generic discord.py.

---

## Bot Class & Shared Resources

`Bot` extends `commands.AutoShardedBot`. All shared resources are attributes on `bot`:

```python
bot.db_pool    # asyncpg.Pool
bot.redis      # redis.asyncio.Redis (decode_responses=True)
bot.yaml_config  # dict from config.yaml (read-only)
bot.config     # ConfigManager instance
bot.premium    # PremiumManager instance
```

Cogs receive `bot` in `__init__` and store references locally:

```python
class MyCog(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.db_pool = bot.db_pool
        self.redis = bot.redis
        self.yaml_config = bot.yaml_config  # only if needed
```

`bot.config` and `bot.premium` are initialized in `setup_hook()` after cogs load — access them via `self.bot.config` at call time, never store them in `__init__`.

---

## Cog Structure

Every cog file:

```python
from __future__ import annotations
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from src.checks import is_owner, is_management  # import only what's used

if TYPE_CHECKING:
    from main import Bot


class MyCog(commands.Cog):
    def __init__(self, bot: Bot):
        self.bot: Bot = bot
        self.db_pool = bot.db_pool
        self.redis = bot.redis


async def setup(bot: commands.Bot):
    await bot.add_cog(MyCog(bot))
```

Place files in `cogs/`. Bot auto-loads all `.py` files in that directory not starting with `_`.

---

## Commands

### Slash Commands

```python
@discord.app_commands.command(name="name", description="Description.")
@discord.app_commands.checks.cooldown(1, 10)
async def my_command(self, interaction: discord.Interaction):
    await interaction.response.send_message("...", ephemeral=True)
```

### Command Groups

```python
class MyCog(commands.Cog):
    myGroup = discord.app_commands.Group(name="group", description="Group description.")

    @myGroup.command(name="sub", description="Subcommand.")
    @discord.app_commands.checks.cooldown(1, 10)
    async def sub(self, interaction: discord.Interaction):
        ...
```

### Prefix Commands

```python
@commands.command(name="ping")
@commands.cooldown(1, 10)
async def ping(self, ctx: commands.Context):
    await ctx.send("...")
```

### Cooldowns

**Every public command must have `cooldown(1, 10)`** — one use per 10 seconds.

- Slash: `@discord.app_commands.checks.cooldown(1, 10)`
- Prefix: `@commands.cooldown(1, 10)`

Cooldown errors are caught by `ErrorHandler` — don't handle them in the command.

### Interaction Responses

- First response: `await interaction.response.send_message(...)` or `.defer()`
- After defer or second message: `await interaction.followup.send(...)`
- Operations taking >3s: `await interaction.response.defer(ephemeral=True)` first

### Parameter Descriptions

```python
@discord.app_commands.describe(
    guild_id="The target guild ID",
    reason="Reason for this action"
)
```

### Guild ID Arguments

Discord delivers slash command integer args as strings. Type-hint as `str` and cast to `int` immediately:

```python
async def cmd(self, interaction: discord.Interaction, guild_id: str):
    gid = int(guild_id)
    # use gid for DB queries and Python logic
    # use str(gid) or f"{gid}" for Redis keys
```

Never type-hint as `int` for guild IDs — Discord snowflakes can exceed JS safe integer range and arrive as strings.

---

## Permission Checks

All checks in `src/checks.py`:

```python
from src.checks import is_owner, is_guild_owner, is_management
```

| Check | Who passes |
|-------|-----------|
| `@is_owner()` | Bot owner only |
| `@is_guild_owner()` | Guild owner or bot owner |
| `@is_management()` | Admin, Manage Guild, or bot owner |

All raise `discord.app_commands.MissingPermissions` on failure — caught by `ErrorHandler`.

---

## Redis Caching

See [references/caching.md](references/caching.md) for pipelines, sorted sets, and stampede prevention.

### Key Naming

```python
cache_ver = self.yaml_config['cache']['cache_version']  # e.g. "v1"
key = f"{cache_ver}:thing:{guild_id}"
```

Established keys:

| Key | Type | TTL |
|-----|------|-----|
| `config:{guild_id}` | JSON string | 30 days |
| `premium:{guild_id}` | JSON string or `"0"` | 30 days |
| `ads:{guild_id}` | raw text | none |
| `partner_cooldown:{a}:{b}` | exists-only | 172800s |
| `server_last_partner:{guild_id}` | timestamp string | 604800s |
| `warn:{key}:{guild_id}` | exists-only | 21600s |
| `invite:{channel_id}` | URL string | 21600s |
| `{claude_ver}:claude:{ad_hash}` | JSON string | 30 days |
| `bot:guild_ids` | set | none |
| `bot:guild_info` | hash (guild_id → JSON) | none |
| `stats:partners:24h` | sorted set | — |

### Common Operations

```python
# String
val = await self.redis.get(key)
await self.redis.set(key, value, ex=ttl)
await self.redis.set(key, value, nx=True, ex=ttl)  # only if not exists
await self.redis.delete(key)
await self.redis.exists(key)  # returns 0 or 1

# Set
await self.redis.sadd("bot:guild_ids", guild_id)
await self.redis.srem("bot:guild_ids", guild_id)
members = await self.redis.smembers("bot:guild_ids")
hit = await self.redis.sismember("bot:guild_ids", guild_id)

# Hash
await self.redis.hset("bot:guild_info", mapping={str(guild_id): json.dumps(data)})
await self.redis.hdel("bot:guild_info", str(guild_id))
val = await self.redis.hget("bot:guild_info", str(guild_id))

# Sorted set
await self.redis.zadd("stats:partners:24h", {str(ts): ts})
await self.redis.zremrangebyscore("stats:partners:24h", 0, cutoff)
count = await self.redis.zcard("stats:partners:24h")
```

### Cache-Aside Pattern (standard for managers)

```python
async def get(self, guild_id: int) -> dict | None:
    cached = await self.redis.get(f"thing:{guild_id}")
    if cached == "0":           # negative cache
        return None
    if cached:
        return json.loads(cached)
    async with self.db_pool.acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM table WHERE guild_id = $1", guild_id)
    if row is None:
        await self.redis.set(f"thing:{guild_id}", "0", ex=86400)
        return None
    data = dict(row)
    await self.redis.set(f"thing:{guild_id}", json.dumps(data), ex=2592000)
    return data
```

`"0"` negative cache prevents DB hammering on missing entries.

### Invalidation

Delete the key after a write:

```python
await self.redis.delete(f"config:{guild_id}")
```

`bot.config.set()` and `bot.premium.set()` handle invalidation internally — always use those managers instead of writing config/premium rows directly.

---

## Postgres Queries

```python
async with self.db_pool.acquire() as conn:
    row  = await conn.fetchrow("SELECT * FROM table WHERE id = $1", id)
    rows = await conn.fetch("SELECT * FROM table WHERE status = $1", status)
    val  = await conn.fetchval("SELECT COUNT(*) FROM table WHERE guild_id = $1", guild_id)
    await conn.execute("INSERT INTO table VALUES ($1, $2)", v1, v2)
    await conn.executemany("INSERT INTO table VALUES ($1, $2)", [(v1, v2), ...])
```

Always use `$1, $2, ...` — never f-strings or `.format()` in queries.

Rows are dict-like: `row["col"]` or `dict(row)` for JSON.

### Transactions

```python
async with self.db_pool.acquire() as conn:
    async with conn.transaction():
        await conn.execute("UPDATE ...")
        await conn.execute("INSERT ...")
        # auto-rollback on any exception
```

See [references/database.md](references/database.md) for schema reference and bulk op patterns.

---

## Error Handling

`ErrorHandler` (`cogs/errorhandler.py`) catches all errors globally. Don't wrap commands in try/except for expected permission or cooldown errors — let them bubble.

Handled automatically:
- `CommandOnCooldown` → retry timestamp message
- `MissingPermissions` / `CheckFailure` → permission denied message
- `Forbidden` (bot missing perms) → missing perms message
- `TransformerError` → "Failed to resolve" message
- Unknown → logs traceback, shows generic error

Catch only specific business-logic exceptions:

```python
try:
    await conn.execute("INSERT INTO blacklists ...")
except asyncpg.UniqueViolationError:
    await interaction.response.send_message("Already blacklisted.", ephemeral=True)
```

Last error per category (slash/prefix/event) is stored on `ErrorHandler` and inspectable via `/error` (owner only).

---

## YAML Config Access

Read-only at startup. Access via `self.yaml_config`:

```python
self.yaml_config['cache']['cache_version']                   # "v1"
self.yaml_config['cache']['partner_cooldown']                # 172800
self.yaml_config['partner_delay']['default']                 # 21600
self.yaml_config['requirements']['member_role_min_coverage'] # 0.80
self.yaml_config['ai']['model']                              # model id string
self.yaml_config['bot']['prefix']                            # "p!"
self.yaml_config['bot']['support_invite']                    # invite URL
```

Use `yaml_config` values for TTLs and thresholds — don't hardcode them in cog logic.

---

## Task Loops

```python
from discord.ext import tasks

class MyCog(commands.Cog):
    @tasks.loop(seconds=60)
    async def my_loop(self):
        ...

    @my_loop.before_loop
    async def before_my_loop(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self.my_loop.start()

    async def cog_unload(self):
        self.my_loop.cancel()
```

### Distributed Lock

Prevent multiple shards/instances running the same loop body:

```python
acquired = await self.redis.set("lock:my_loop", "1", nx=True, ex=55)
if not acquired:
    return
try:
    # do work
finally:
    await self.redis.delete("lock:my_loop")
```

TTL should be slightly shorter than loop interval so a crashed instance releases before next tick.

---

## Prompts / Claude Integration

If `src/prompts.py` changes, update `claude_cache_version` in `config.yaml`. Scan result cache key is `{claude_cache_version}:claude:{ad_hash}`.

---

## Project Conventions

- `on_message` lowercases content before `process_commands` — prefix commands match case-insensitively.
- Guild IDs are `int` in Python; cast to `str` only for Redis keys via f-string.
- Use `bot.config` / `bot.premium` managers — never read `guild_config` or `premium` tables directly in a cog.
- `src/constants.py` owns `ALL_PINGS` / `VALID_PINGS` — import, don't redefine.
- Owner-only commands go in `cogs/owneronly.py` with `@is_owner()`.
- Early access check: `await self.redis.sismember("bot:early_access_guilds", str(guild_id))`.
