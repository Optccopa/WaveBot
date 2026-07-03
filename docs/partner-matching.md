# Partner Matching

## Overview

The partner loop fires every 60 seconds (`@tasks.loop(seconds=60)`), but actual partnership work is gated by a Redis NX key `last_partner_run` with TTL `cache.redis_lock`. Only one run executes per TTL window; subsequent loop ticks that find the key present are skipped silently.

Each run calls `index_ad()` per guild inline as it builds the eligible pool, then matches servers in pairs and sends ads.

## Eligibility

A guild must pass all of these to enter matching:

1. Not blacklisted (checked against `blacklists` table in Postgres)
2. Has a config row in `guild_config`
3. `partner_channel`, `ad_channel`, `member_role`, `partner_ping_role` all resolve to real Discord objects
4. `partner_channel` is a `TextChannel` (not a thread, forum, etc.)
5. Bot has `Send Messages` and `Mention Everyone` in `partner_channel`
6. Has a cached ad in Redis at `ads:{guild_id}`
7. Passes `validate_server` checks (member role coverage ≥80%, channel visibility ≥95%, partner ping role coverage ≥8%)

If a guild fails steps 4–7, an embed is sent to its `log_channel` explaining why.

## Matching Algorithm

`match_servers` uses greedy maximum matching:

1. All possible pairs are generated, cooldowns fetched in one Redis pipeline.
2. An adjacency set is built — only pairs NOT on cooldown are connected.
3. Nodes are sorted most-constrained first (fewest available partners).
4. Greedy: for each unmatched node, pick the partner with the fewest remaining options.

This approximates maximum matching without Blossom complexity. It won't always find the true global maximum but handles the typical small pool sizes well.

## Cooldowns

Cooldown TTL: `cache.partner_cooldown` in `config.yaml` (currently 172800s = 2 days).

Key format: `{cache_version}:partner_cooldown:{min(a,b)}:{max(a,b)}`


## Sending Ads

For each matched pair `(server1, server2)`:

- `server1`'s cached ad is sent to `server2`'s partner channel, with `server1`'s ping appended
- `server2`'s cached ad is sent to `server1`'s partner channel, with `server2`'s ping appended

Ping type is determined by `get_req()` based on member counts. The larger server (host) gets a lighter ping; the smaller server (guest) gets a heavier ping scaling with size difference.

Ping tiers (reference scale 2300 members):
- ≤400 scaled: host pings `none`
- ≤800: host pings `partner`
- ≤1700: host pings `here`
- ≤2000: host pings `partnerhere`
- >2000: host pings `member`

Guest always pings `member`.

Pings in the stored ad text are stripped before storage — `parse_ping` adds the correct ping at send time based on each server's config.

After each pair is sent, `asyncio.sleep(delays.partner_pair)` (default 3s) runs unconditionally to pace Discord API calls.

Each ad message carries an `AddBotView` with three buttons:
- **Add WaveBot** — static persistent button (`custom_id: wavebot:add_bot`), shows invite embed.
- **Partner Info** — `discord.ui.DynamicItem` button (`custom_id: wavebot:partner_info:{partnership_id}`). Before sending, `partner()` inserts a snapshot row into the `partnerships` table (both guild ids/names, member counts, pings used, host, timestamp) and encodes the row id in the custom_id — survives restarts, values are frozen at match time. If either send fails the row is deleted. Clicking replies with an ephemeral embed (cache-aside via Redis `partner_info:{id}`, 30-day TTL, `"0"` negative cache) showing both servers' names, ids, member counts, and viewer-relative ping direction ("Pinged here" vs "Pinged there"). Rate limited 1 click / 10s per user via Redis NX key.
- **Report** — `discord.ui.DynamicItem` button (`custom_id: wavebot:report:{partnership_id}`), same rate limit. Opens a modal (category dropdown, reason, rule broken). On submit (deferred, all replies via followup): dedupe via Redis `reported:{partnership_id}:{user_id}` (30d, set only after a successful insert) backed by a unique index on `reports (partnership_id, reporter_id)` — Redis flush can't enable re-reports. Row inserted into `reports`, embed posted to `channels.reports` (config.yaml, send failure logged, reporter still acked) with owner-only **Blacklist** / **Dismiss** action buttons. Both action buttons open a `ReportActionModal` (owner check first) with a required reason field. On submit the modal defers, guards with `WHERE status = 'open' ... RETURNING` so a second submission (or the other action) gets "already handled" instead of double-writing, stores the reason in `reports.handled_reason`, and wraps DB work in try/except (failures logged + ephemeral error reply via `_interaction_error_reply`). Blacklist additionally upserts into `blacklists` (reason included), invalidates the `partner_info:{pid}` cache, and leaves the guild last (leave failure logged); Dismiss just marks the report. Both edit the report embed (handler + reason), then **DM the reporter** with the outcome and the moderator note (closed DMs logged, not fatal). Both report modals have `on_error` handlers so DB/network failures reply instead of stranding the interaction. The reported server is resolved as the partnership member that isn't the guild where the button was clicked. One report per user per partnership. Registered via `bot.add_dynamic_items(PartnerInfoButton)` in `cog_load`. `/partner broadcast` messages carry only the Add WaveBot button — no matching data exists there.

## Concurrency

Two locks prevent double-runs:

- `asyncio.Lock` (`self._partner_lock`): prevents concurrent runs within the same process instance. Checked before acquiring, not just inside the `async with` block, so the check itself is non-blocking.
- Redis NX key `last_partner_run` (TTL = `cache.redis_lock`, 19800s): prevents concurrent runs across multiple bot instances (multi-shard / multi-container).

`forceloop` acquires the asyncio lock and force-sets the Redis key, bypassing the NX check.

## Commands

- `/partner reqs [membercount]` — public, shows ping-tier ranges from `get_req` for a given member count (default 1000)
- `/partner ad <guild_id>` — public, views the cached ad for a server; attempts `index_ad` on cache miss before responding
- `/partner status` — management, shows why a server may not be getting partnered
- `/partner force <id1> <id2>` — owner only, forces a partner send between two specific servers
- `/partner loopforce` — owner only, runs a full partner round immediately (acquires the asyncio lock, skips the NX Redis check)
- `/partner indexads` — owner only, re-indexes all server ads and returns a summary (total, cached, missing ad, missing channel, no config)
- `/partner broadcast <guild_id>` — owner only, sends a server's cached ad to every other server's partner channel; 24h command cooldown, 1s sleep between sends
