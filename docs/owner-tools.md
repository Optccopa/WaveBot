# Owner Tools

All commands in this file require `is_owner()` — the bot application owner check. They are defined in `cogs/owneronly.py` unless noted.

## `/servers` Group

### `/servers overview`

Lists every guild the bot is in. For each guild:
- Member count
- **Needs X/week** — how many times `partner_delay` fits into a week (`round(604800 / partner_delay)`)
- **Available X/week** — how many other guilds this server is not on pair-cooldown with (counts all guilds; pair cooldowns fetched in one Redis pipeline)
- **Next** — Discord relative timestamp for when this server is next eligible (`last_partner + partner_delay`), or "now" if never partnered

Paginated in chunks of 25 guilds per embed.

### `/servers invite <server_id>`

Gets a Discord invite for a server. Tries the configured partner channel first, then falls back to any text channel where the bot has `Create Instant Invite`. Returns an existing invite if one exists, otherwise creates a 7-day invite. Returns an error if no usable channel is found or the bot is missing permissions.

### `/servers debug <server_id>`

Detailed debug embed for a single server:
- Guild info: ID, member count, owner
- Raw config JSON
- Channel resolution status (partner_channel, ad_channel)
- Role resolution status (member_role, partner_ping_role)
- Cached ad (first 200 chars)
- Invite URL
- Overall ready status

Unresolved IDs are flagged with the raw ID so you can identify stale config values.

### `/servers debugall`

Runs the same debug output as `/servers debug` for every guild in sequence. Sends one embed per guild. Use with caution on large fleets — can hit message rate limits.

### `/servers leave <server_id>`

Forces the bot to leave a specific server. Bot sends a confirmation message first, then leaves.

---

## `/blacklist` Group

### `/blacklist add <guild_id> <reason>`

Adds a guild to the `blacklists` table. If the bot is currently in that guild, it leaves immediately after inserting the row. The guild owner receives a DM explaining the reason and where to appeal.

`ON CONFLICT DO UPDATE` — re-adding an already-blacklisted guild updates the reason and `added_by`.

### `/blacklist remove <guild_id>`

Deletes the guild from `blacklists`. Does not cause the bot to rejoin.

### `/blacklist check <guild_id>`

Queries `blacklists` and returns the reason if blacklisted, or "Not blacklisted" otherwise.

---

## `/whitelist` Group

Whitelisted links are stripped from ad text before scanning and before storage. This prevents common link shorteners or affiliate links from triggering false positives.

### `/whitelist add <link>`

Inserts into `whitelisted_links` table (`ON CONFLICT DO NOTHING`) and adds to Redis set `whitelisted_links`. Both Postgres and Redis are updated atomically.

### `/whitelist remove <link>`

Deletes from `whitelisted_links` table and removes from Redis set `whitelisted_links`.

### `/whitelist list`

Lists all rows from `whitelisted_links` with the Discord user who added each link.

---

## `/earlyaccess` Group

See [early-access.md](early-access.md) for full context on the early access system.

### `/earlyaccess add <guild_id> <user> <reason>`

Grants a server early access to bypass `requirements.minimum_membercount`. Inserts into `early_access` table and adds to Redis set `bot:early_access_guilds`. `user` is the Discord user to attribute the grant to (stored as `user_id`).

`ON CONFLICT DO NOTHING` — does not update an existing record.

### `/earlyaccess remove <guild_id>`

Deletes from `early_access` table and removes from Redis set `bot:early_access_guilds`.

### `/earlyaccess list`

Lists all rows from `early_access` with guild name (resolved from bot cache), member count, reason, and attributed user. Paginated in chunks of 25.

---

## `/partner broadcast <guild_id>` (defined in `cogs/partner.py`)

Sends a server's cached ad to the partner channel of every other guild the bot is in. Skips guilds with no config or no valid partner channel. Reports sent/failed count on completion.

- 24h command cooldown (per user via `@discord.app_commands.checks.cooldown`)
- Does not set pair cooldowns — broadcast sends are not tracked as partnerships
- Sleeps 1s between sends to avoid rate limiting

---

## `p!exec <code>` (prefix command, defined in `cogs/owneronly.py`)

Executes arbitrary async Python code in the bot's context. Available environment:

```python
{
    "bot": self.bot,
    "ctx": ctx,
    "discord": discord,
    "asyncio": asyncio,
    "db_pool": self.bot.db_pool,
    "redis": self.bot.redis,
    "guild": ctx.guild,
    "channel": ctx.channel,
    "author": ctx.author,
    "message": ctx.message,
}
```

Code is wrapped in `async def _exec():` and `await`ed. On exception, sends a two-field embed: traceback body and exception line. Output is not captured — use `await ctx.send(...)` inside the code if you need to see a value.

Example: `p!exec await ctx.send(len(bot.guilds))`
