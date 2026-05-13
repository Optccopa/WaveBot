# Known Issues

## Effective Partner Interval — Not Configurable at Runtime

**File:** `cogs/partner.py`

The loop fires every 60 seconds but the actual work interval is controlled by the Redis NX key `last_partner_run` with TTL `cache.redis_lock`. To change how often partnerships run, `cache.redis_lock` in `config.yaml` must be edited and the bot redeployed. The 60-second tick rate itself is a hardcoded literal and cannot be read from config.

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

## Discord 503 Errors Crash Partner Loop — FIXED

Previously `log_channel.send()` calls in `index_ads()` and `_run_partner_round()` only caught `discord.Forbidden`. A transient `discord.DiscordServerError` (503) would propagate up and abort the entire loop, surfacing as a `CommandInvokeError`. All such calls now catch `discord.HTTPException` (parent of both 403 and 503) so transient Discord errors are silently skipped and the loop continues.

## No Retry if Partner Send Fails Halfway

**File:** `cogs/partner.py`, `partner()` method

If `channel1.send(ad2)` succeeds but `channel2.send(ad1)` fails, the cooldown is not set. This means server1 received server2's ad, but server2 did not receive server1's ad, and neither is on cooldown — so they may partner again next round, giving server1 a second copy of server2's ad. There is no rollback or half-success tracking.

## Blacklist Check Skips Bot's Own Guild IDs

The blacklist is checked per-guild in the loop, but `bot:guild_ids` Redis set (used by the site to show which guilds have the bot) is not cleared of blacklisted guilds. Blacklisted guilds appear in the site UI as bot-present guilds.
