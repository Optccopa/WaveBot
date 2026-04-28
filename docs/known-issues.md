# Known Issues

## Partner Loop Interval — Not Configurable at Runtime

**File:** `cogs/partner.py`, line 547

```python
@tasks.loop(seconds=21600)
```

`tasks.loop` requires a literal value at decoration time. The 6-hour interval cannot be read from `config.yaml` without refactoring to use `tasks.loop` with a `seconds=0` and manually sleeping inside the loop body. Currently the only way to change the interval is a code edit and redeploy.

## Ad Scan Result Does Not Gate Distribution

**File:** `cogs/partner.py`, `index_ads()` / `index_ad()`

Ads are scanned by Claude Haiku and the result is cached, but `sus: true` does not prevent the ad from being stored and sent during partner rounds. The scan result is logged only. This is intentional for now but means the moderation system has no enforcement layer.

## Validation Fails Open on Site

**File:** `site/app.py`, lines 401–413

If the bot internal HTTP server is unreachable (bot crashed, network issue), the `try/except` around the validation call silently swallows the error and saves the config without validation. This is intentional (resilience over strictness) but means an invalid config can be saved when the bot is down.

## guild_info Redis Hash Has No TTL

**File:** `main.py`, `on_ready` / `on_guild_join`

`bot:guild_info` is a Redis hash storing guild name/icon/member_count. It is populated on ready and updated on join/leave. If a guild changes its name or member count between bot restarts, the stale value remains until the bot restarts and calls `on_ready` again. There is no scheduled refresh.

## member_count in guild_info Stale

Related to above: `guild.member_count` at ready time is accurate, but between ready events it is not updated in the Redis hash. The web panel displays stale member counts if the bot has been running for a while without a restart.

## Blacklist Check Skips Bot's Own Guild IDs

The blacklist is checked per-guild in the loop, but `bot:guild_ids` Redis set (used by the site to show which guilds have the bot) is not cleared of blacklisted guilds. Blacklisted guilds appear in the site UI as bot-present guilds.

## Matching Bias in Greedy Algorithm

**File:** `cogs/partner.py`, lines 206-207

Greedy matching shuffles servers randomly, then sorts by constraint. However, the sort uses guild_id as tie-breaker (implicit in Python's stable sort), creating deterministic bias for servers with equal constraint levels. Randomized comparator recommended to eliminate bias.

## Distributed Lock Deadlock on Instance Crash

**File:** `cogs/partner.py`, lines 559-562

Multi-instance bot uses Redis NX key `last_partner_run` with 10800s TTL to prevent concurrent loop runs. If a bot instance crashes while holding the lock, the key persists for 3 hours, silently blocking all other instances from running the partner loop. No automatic deadlock detection or alert mechanism.
