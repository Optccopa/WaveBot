# Known Issues

## Partner Loop Interval — Not Configurable at Runtime

**File:** `cogs/partner.py`, line 549

```python
@tasks.loop(seconds=21600)
```

`tasks.loop` requires a literal value at decoration time. The 6-hour interval cannot be read from `config.yaml` without refactoring to use `tasks.loop` with a `seconds=0` and manually sleeping inside the loop body. Currently the only way to change the interval is a code edit and redeploy.

## Ad Scan Result Does Not Gate Distribution

**File:** `cogs/partner.py`, `index_ads()` / `index_ad()`

Ads are scanned by Claude Haiku and the result is cached, but `sus: true` does not prevent the ad from being stored and sent during partner rounds. The scan result is logged only. This is intentional for now but means the moderation system has no enforcement layer.

## Sat-Out Reroll Clears Cooldowns Permanently

**File:** `cogs/partner.py`, lines 392–404

When sat-out servers are rerolled, their pairwise cooldowns are deleted. If the reroll fails to match them (e.g., only one sat-out server, or the two sat-out servers have each other on cooldown for some other reason), the cooldowns are still cleared but no partnership happened. This means servers that were on cooldown for a valid reason (they recently partnered) may partner again sooner than intended.

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
