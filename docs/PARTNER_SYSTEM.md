# Partner System

## Overview
WaveBot matches servers on a 6-hour cycle, exchanging ads cross-server. Each server has a configurable personal delay between partnership events (default 6 hours, 1 hour minimum, 1 week maximum).

## Loop Interval
- **Loop frequency:** Every 6 hours (21600 seconds)
- **Distributed lock TTL:** 25200 seconds (~7 hours) — prevents concurrent runs in multi-shard setups

## Per-Server Delay

Each server can configure how long to wait after receiving a partner before becoming eligible again via `/config set partner_delay <seconds>`.

**Constraints:**
- Minimum: 3600 seconds (1 hour)
- Maximum: 604800 seconds (7 days)
- Default: 21600 seconds (6 hours)

After a successful partnership, Redis keys are set:
- `last_partnered:{guild_id}` — expires after `partner_delay` seconds
- Server is ineligible for matching while this key exists

## Sat-Out Server Behavior
Servers that are eligible but don't find a match (due to pairwise cooldowns) do **not** get a `last_partnered` key set. They remain eligible and are retried in the next 6-hour cycle.

## Pairwise Cooldown
After servers exchange ads, they are placed on a pairwise cooldown:
- Redis key: `{cache_version}:partner_cooldown:{min_id}:{max_id}`
- TTL: 259200 seconds (3 days) — prevents re-pairing too frequently

## Configuration
Server admins can adjust their delay via:
```
/config set partner_delay 86400
```

View current settings:
```
/config view
```

## Matching Algorithm
1. Hourly loop checks all eligible guilds (no active `last_partnered` key)
2. Filters out blacklisted, unconfigured, or failing validation
3. Greedy matching: highest-constrained servers matched first
4. Pairwise cooldowns prevent recent pairs from re-matching
5. Sat-out servers stay eligible for next round

## Requirements for Partnership
- Server has valid config (partner channel, ad channel, member role, partner ping role)
- At least 80% of members have the member role
- At least 8% of members have the partner ping role
- At least 50 members (minimum_membercount from config)
- Partner channel is visible to the member role
- No active blacklist, no active pairwise cooldown
- No active personal delay (`last_partnered:` key)
