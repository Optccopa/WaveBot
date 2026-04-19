# Partner Matching

## Overview

The partner loop runs every 6 hours (`@tasks.loop(seconds=21600)`). It cannot be configured at runtime without a code change — the interval is hardcoded because `tasks.loop` requires a literal at decoration time.

Each run collects eligible servers, matches them in pairs, and sends each server's cached ad to the other server's partner channel.

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

Cooldown TTL: `times.partner_cooldown_ttl` in `config.yaml` (currently 259200s = 3 days).

Key format: `{cache_version}:partner_cooldown:{min(a,b)}:{max(a,b)}`

### Sat-Out Reroll

If 2+ servers land in `sat_out` (all their cooldowns were active), their inter-cooldowns are cleared and matching is retried for that subset only. This prevents servers from being silently skipped when everyone in the pool has partnered each other recently.

One sat-out server is normal and not rerolled — it will partner next round.

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

## Concurrency

Two locks prevent double-runs:

- `asyncio.Lock` (`self._partner_lock`): prevents concurrent runs within the same process instance. Checked before acquiring, not just inside the `async with` block, so the check itself is non-blocking.
- Redis NX key `last_partner_run` (TTL = `times.redis_lock_ttl`, 10800s): prevents concurrent runs across multiple bot instances (multi-shard / multi-container).

`forceloop` acquires the asyncio lock and force-sets the Redis key, bypassing the NX check.

## Commands

- `/partner status` — guild owners see why their server may be skipped
- `/partner loopinfo` — shows next scheduled run time
- `/partner loopforce` — bot owner only, runs a loop immediately
- `/partner force <id1> <id2>` — bot owner only, forces a specific pair
- `/partner ad <guild_id>` — bot owner only, views a cached ad
