# Code Audit Report

## Summary

The codebase is a Discord bot (WaveBot) that handles server partnerships, ad scanning via regex + Claude AI, and configuration management. Overall architecture is solid — Redis caching is used appropriately, Postgres backs persistent data, and async patterns are used correctly. However, there are **2 critical bugs** that will crash at runtime (unbound variable, None dereference), **4 high-severity** issues including real credentials in a plaintext file and a broken requirement, and several medium/low quality and correctness issues. Total: **2 Critical, 4 High, 7 Medium, 6 Low = 19 issues**.

---

## Issues

---

### [CRITICAL] `on_app_command_error` has unbound variable and wrong message path

**File:** `cogs/errorhandler.py` (Lines 26–43)
**Category:** Bug

**Description**
The handler uses two separate `if` statements instead of `if/elif/else`. The `else` is paired with the second `if` (CommandOnCooldown), not the first. This causes two distinct bugs:

1. When error is `MissingPermissions`: the first `if` sets `msg`, then the second `if` is False so the `else` runs and **overwrites `msg`** with the generic error string. The user sees the wrong message.
2. When error is `CommandOnCooldown`: the cooldown response is sent, the `else` does not run, so `msg` is **never assigned**. The final `interaction.followup.send(msg, ...)` raises `UnboundLocalError`, which itself gets swallowed — leaving the interaction with no second response and a silent crash.

**Why It's Bad**
Every `MissingPermissions` error shows the wrong message. Every `CommandOnCooldown` error raises an unhandled exception mid-handler after already responding. The error handler crashes silently.

**Proposed Fix**
```python
async def on_app_command_error(self, interaction, error):
    self.last_errors["slash"] = traceback.format_exception(type(error), error, error.__traceback__)

    if isinstance(error, discord.app_commands.MissingPermissions):
        msg = "You don't have permission to use this command."
    elif isinstance(error, discord.app_commands.CommandOnCooldown):
        retry_at = int(time() + error.retry_after)
        await interaction.response.send_message(f"Slow down, Retry at: <t:{retry_at}:R>", ephemeral=True)
        return
    else:
        print("App command error:", repr(error))
        msg = "An unexpected error occurred, if this issue persists please contact support."

    if interaction.response.is_done():
        await interaction.followup.send(msg, ephemeral=True)
    else:
        await interaction.response.send_message(msg, ephemeral=True)
```

---

### [CRITICAL] `addBlacklist` crashes on invalid guild ID and None guild

**File:** `cogs/owneronly.py` (Lines 32–53)
**Category:** Bug

**Description**
Two bugs in `addBlacklist`:

1. If `guild_id` is not a valid integer, `int(guild_id)` inside the `try` raises `ValueError`, which is caught and `interaction.response.send_message("Guild id must be int")` is called. However, execution **does not return** — it continues to the code below. `int(guild_id)` is called again, raises `ValueError` again, is caught by the inner try, and attempts `interaction.response.send_message(embed=embed)` — which throws `InteractionAlreadyResponded`.

2. If `guild_id` is a valid int but the bot is not in that guild, `self.bot.get_guild(int(guild_id))` returns `None`, and `await guild.leave()` raises `AttributeError: 'NoneType' object has no attribute 'leave'`.

Similarly, `checkBlacklist` (line 62–78) has the same ValueError pattern: if the except fires, `row` is never assigned and `if row:` causes `NameError`.

**Why It's Bad**
Both command paths crash with unhandled exceptions on bad input. For `checkBlacklist`, using a non-integer guild ID leaves the interaction unanswered.

**Proposed Fix**
```python
@blacklistGroup.command(name="add")
@is_owner()
async def addBlacklist(self, interaction, guild_id: str, reason: str = "No reason provided"):
    try:
        gid = int(guild_id)
    except ValueError:
        await interaction.response.send_message("Guild id must be an integer", ephemeral=True)
        return

    async with self.db_pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO blacklists (guild_id, reason, added_by) VALUES ($1, $2, $3)"
            " ON CONFLICT (guild_id) DO UPDATE SET reason = $2, added_by = $3",
            gid, reason, interaction.user.id
        )

    guild = self.bot.get_guild(gid)
    if guild:
        await guild.leave()

    embed = discord.Embed(title="Added Blacklist", description=f"Reason: {reason}", color=discord.Color.fuchsia())
    await interaction.response.send_message(embed=embed, ephemeral=True)
```

---

### [HIGH] Whitelisted links Redis set not synced from Postgres on startup

**File:** `cogs/cache_ads.py` (Line 69), `cogs/owneronly.py` (Lines 83–89)
**Category:** Bug

**Description**
Whitelisted links are stored persistently in Postgres (`whitelisted_links` table) and cached in a Redis set (`whitelisted_links`). When `addWhitelist` is called it writes to both. However, on bot startup (or after a Redis flush/restart), the Redis set is **never populated from Postgres**. `index_ads` reads `await self.redis.smembers("whitelisted_links")` which returns an empty set, so no links are filtered from ads until `addWhitelist` is called again.

**Why It's Bad**
After any Redis restart, all previously whitelisted links are effectively un-whitelisted until the owner manually re-adds them. Ads containing those links will be flagged as violations.

**Proposed Fix**
In `setup_hook` or `cog_load` for `AdLooper`, sync Postgres → Redis:
```python
async def cog_load(self):
    async with self.bot.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT link FROM whitelisted_links")
    if rows:
        await self.redis.sadd("whitelisted_links", *[r["link"] for r in rows])
    ...
```

---

### [HIGH] `requirements.txt` has wrong package name for `python-dotenv`

**File:** `requirements.txt` (Line 5)
**Category:** Dependency

**Description**
The requirement is listed as `dotenv`, but the correct PyPI package name is `python-dotenv`. The `dotenv` package on PyPI is an unrelated, unmaintained stub. Additionally, `asyncio` is Python's standard library and does not belong in `requirements.txt`.

**Why It's Bad**
A fresh `pip install -r requirements.txt` will install the wrong `dotenv` package (or fail), and `load_dotenv()` will not be available. The bot won't load environment variables correctly. No actual crash is visible until something tries to import `dotenv`.

**Proposed Fix**
```
discord.py
asyncpg
redis
python-dotenv
anthropic
```

---

### [HIGH] Live API credentials stored in plaintext `.env`

**File:** `.env` (Lines 1–2)
**Category:** Security

**Description**
The `.env` file contains a real Discord bot token and a real Anthropic API key in plaintext. The file is listed in `.gitignore` and not committed to the repository, but it exists on the local filesystem.

**Why It's Bad**
If the project folder is zipped, shared, uploaded, or synced via a secondary tool (cloud backup, file share), both credentials are exposed. A leaked Discord token allows full bot impersonation including sending messages, leaving guilds, and reading all accessible messages. A leaked Anthropic API key results in unauthorized charges and potential account suspension.

**Proposed Fix**
Store credentials only in environment variables provided by the deployment environment (Docker secrets, Railway/Heroku config vars, etc.). Rotate both credentials immediately if there is any doubt they have been exposed. Add a `.env.example` file with placeholder values for documentation.

---

### [MEDIUM] `print()` used with printf-style format strings — formatting silently ignored

**File:** `cogs/cache_ads.py` (Lines 54, 116)
**Category:** Bug

**Description**
Two `print()` calls use C-style `%s` format string syntax:
- `print("Failed to parse claude haiku response for ad: %.100s", ad)`
- `print("[cache_ads] guild %s scan result: %s", guild.id, response)`

Python's `print()` does not do printf-style interpolation. It prints the format string and the extra arguments as separate comma-separated values. The resulting output is garbled and useless for debugging.

**Why It's Bad**
The intended truncation (`%.100s`) does not occur. The log line becomes two items joined by a space, making log parsing unreliable.

**Proposed Fix**
```python
print(f"Failed to parse claude haiku response for ad: {ad[:100]}")
print(f"[cache_ads] guild {guild.id} scan result: {response}")
```

---

### [MEDIUM] `guild.owner` can be `None` before `guild.leave()` in `on_guild_join`

**File:** `main.py` (Lines 104–129)
**Category:** Bug

**Description**
In `on_guild_join`, the code calls `guild.owner.send(...)` inside a `try/except discord.Forbidden` block. However, `guild.owner` can be `None` if the owner is not cached (e.g., the guild was not chunked yet, or the owner left). An `AttributeError: 'NoneType' object has no attribute 'send'` is not a `discord.Forbidden` and will propagate uncaught.

**Why It's Bad**
An uncaught `AttributeError` propagates to the event dispatcher and gets logged as an unhandled event error. More importantly, the `finally: await guild.leave()` still runs, so the bot leaves correctly — but the exception is unnecessarily noisy and could mask other issues.

**Proposed Fix**
```python
if guild.owner:
    try:
        await guild.owner.send(...)
    except discord.Forbidden:
        pass
await guild.leave()
```
Remove the `finally` block; `guild.leave()` should always be called unconditionally after the owner DM attempt.

---

### [MEDIUM] No TTL on Redis config cache — stale data persists indefinitely

**File:** `src/configmanager.py` (Lines 28, 55)
**Category:** Performance

**Description**
`ConfigManager.get()` writes to Redis with no expiry: `await self.redis.set(key, json.dumps(data))`. If a guild's config is changed directly in Postgres (e.g., by a migration or manual admin action), the Redis cache will never expire and will serve stale data until `invalidate()` is explicitly called. `invalidate()` is not called anywhere in the codebase.

**Why It's Bad**
Any direct database modification is invisible to the running bot. Stale cached configs cause incorrect behavior (wrong channels, roles, etc.) that is very hard to diagnose.

**Proposed Fix**
Add a TTL to both writes:
```python
await self.redis.set(key, json.dumps(data), ex=3600)  # 1 hour TTL
```
Also call `self.invalidate(guild_id)` before re-reading in `set()`, or write the new data directly without re-fetching.

---

### [MEDIUM] No TTL on Claude scan cache — stale AI results persist forever

**File:** `cogs/cache_ads.py` (Line 112)
**Category:** Performance

**Description**
`await self.redis.set(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}", response)` stores AI scan results with no expiry. These entries accumulate indefinitely. The `CACHE_VER_CLAUDE` version bump is the only invalidation mechanism, but old keys from previous versions are never deleted.

**Why It's Bad**
Redis memory grows unboundedly with one entry per unique ad hash. After a SCAN_PROMPT update, old cached verdicts remain in memory under the old version prefix, wasting memory without being referenced.

**Proposed Fix**
Add a TTL matching the ad loop interval:
```python
await self.redis.set(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}", response, ex=60 * 60 * 24 * 7)  # 7 days
```

---

### [MEDIUM] `debug_server`, `leave_server`, `removeBlacklist` call `int()` without error handling

**File:** `cogs/owneronly.py` (Lines 177, 330, 58)
**Category:** Bug

**Description**
`debug_server`, `leave_server`, and `removeBlacklist` all call `int(server_id)` directly without a try/except. If a non-numeric string is passed, `ValueError` is raised and the interaction is left unanswered (no response is sent before the exception propagates to the error handler).

**Why It's Bad**
The interaction times out from Discord's perspective and the bot reports an unhandled error. Owner-only commands should still validate input gracefully.

**Proposed Fix**
```python
try:
    gid = int(server_id)
except ValueError:
    await interaction.followup.send("Server ID must be a number.", ephemeral=True)
    return
```

---

### [MEDIUM] "(Testing Placeholder)" left in production ad content

**File:** `cogs/partner.py` (Lines 209–210)
**Category:** Bug

**Description**
The ads sent to partner channels include literal placeholder text:
```python
ad1 = f"{raw_ad1}\n\n{r['server_b']} (Testing Placeholder)"
ad2 = f"{raw_ad2}\n\n{r['server_a']} (Testing Placeholder)"
```
`r['server_b']` and `r['server_a']` are ping tier labels (`"none"`, `"partner"`, `"here"`, `"member"`) — not actual Discord mentions or formatted pings. No real role pings are ever sent.

**Why It's Bad**
Partner channels receive ads with a meaningless footer like `"member (Testing Placeholder)"` instead of an actual role mention. The partnering feature is effectively broken for its core purpose of pinging the appropriate role.

**Proposed Fix**
Replace with actual role mention resolution based on the ping tier:
```python
def resolve_ping(guild, config, tier):
    if tier == "none":
        return ""
    elif tier == "partner":
        role = guild.get_role(config.get("partner_ping_role"))
    elif tier in ("here", "partnerhere"):
        return "@here"
    elif tier == "member":
        role = guild.get_role(config.get("member_role"))
    return role.mention if role else ""
```

---

### [LOW] `is_owner()` duplicated between `src/checks.py` and `cogs/errorhandler.py`

**File:** `cogs/errorhandler.py` (Lines 4–8)
**Category:** Code Quality

**Description**
`is_owner()` is defined identically in both `src/checks.py` and `cogs/errorhandler.py`. The version in `errorhandler.py` is unused by the rest of the file (the `lasterror` command uses it via decorator, but `checks.py` version is already available).

**Why It's Bad**
If the ownership check logic ever needs to change, it must be updated in two places. This is the definition of duplicated logic.

**Proposed Fix**
Remove the local definition from `errorhandler.py` and import from `src.checks`:
```python
from src.checks import is_owner
```

---

### [LOW] `import random` appears after first use in `tests/matchtest.py`

**File:** `tests/matchtest.py` (Lines 18, 24)
**Category:** Code Quality

**Description**
`random.choice(pool)` is called at line 18 inside `match_servers()`, but `import random` appears at line 24. This works at runtime because the import is executed before the function is called, but it is confusing and violates PEP 8 (all imports at top of file).

**Why It's Bad**
Future readers or linters will flag this as a potential NameError risk. It's a maintenance hazard.

**Proposed Fix**
Move `import random` to the top of the file.

---

### [LOW] Setup wizard views lack `interaction_check` for user identity validation

**File:** `cogs/setup.py` (Multiple view classes)
**Category:** Security

**Description**
None of the `discord.ui.View` subclasses in `setup.py` implement `interaction_check`. Discord ephemeral messages are only visible to the original invoker, so in practice another user cannot interact with them. However, if Discord's ephemeral guarantee ever fails (e.g., in certain edge cases with shared interactions, or future API changes), any user in the guild could potentially advance or confirm another user's setup flow.

**Why It's Bad**
Low-likelihood but the defense-in-depth principle is not followed. Bot security should not rely solely on Discord's ephemeral visibility.

**Proposed Fix**
Add to each view class:
```python
async def interaction_check(self, interaction: discord.Interaction) -> bool:
    return interaction.user == self.original_user
```

---

### [LOW] `from src.prompts import *` wildcard import in test file

**File:** `tests/claude.py` (Line 4)
**Category:** Code Quality

**Description**
`from src.prompts import *` imports everything from `prompts.py` into the module namespace, including `SCAN_PROMPT` and `RULE_PATTERNS`. Wildcard imports pollute the namespace and make it impossible to tell at a glance where a name comes from.

**Why It's Bad**
If `prompts.py` ever adds a new name that conflicts with a local variable in `claude.py`, it will silently shadow it. Explicit imports are always preferable.

**Proposed Fix**
```python
from src.prompts import SCAN_PROMPT, RULE_PATTERNS
```

---

### [LOW] `asyncio` listed in `requirements.txt` — it is a stdlib module

**File:** `requirements.txt` (Line 2)
**Category:** Dependency

**Description**
`asyncio` is part of the Python standard library since Python 3.4 and cannot be installed via pip. Listing it in `requirements.txt` does nothing on modern Python and may cause confusion for contributors.

**Why It's Bad**
On some older pip versions or non-CPython runtimes, attempting to install `asyncio` could resolve to an outdated third-party shim instead of the standard library module, causing subtle compatibility issues.

**Proposed Fix**
Remove `asyncio` from `requirements.txt`.
