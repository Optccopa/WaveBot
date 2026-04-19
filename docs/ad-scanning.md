# Ad Scanning

## Overview

`cogs/cache_ads.py` runs every 3 hours (`@tasks.loop(seconds=10800)`). It scans each guild's ad channel, finds the most recent message containing a URL, scans it for policy violations, and caches the cleaned ad text in Redis.

## Ad Discovery

For each guild with a config:

1. Reads the last 10 messages from `ad_channel`
2. Takes the first message matching `https?://\S+`
3. Strips whitelisted links (stored in Redis set `whitelisted_links`, seeded from Postgres `whitelisted_links` table on cog load)
4. Computes a SHA-256 hash (first 12 chars) for cache keying

If no ad is found, an embed is sent to `log_channel`.

## Scanning Pipeline

### Step 1 — Regex Pre-scan

`RULE_PATTERNS` from `src/prompts.py` defines rule → pattern lists. If any pattern matches, the ad is flagged immediately with confidence 0.95 and the AI call is skipped.

### Step 2 — Claude Haiku

If regex passes, the ad is sent to `claude-haiku-4-5-20251001` with prompt caching enabled (`cache_control: ephemeral` on the system prompt). The model responds in JSON format (prefilled with `{` to force JSON output).

Cache key: `{claude_cache_version}:claude:{ad_hash}` — TTL 30 days. Scan results are reused until the ad content changes.

Timeout: 30 seconds per scan via `asyncio.wait_for`. On timeout, `sus=False` with confidence 0.5 is returned to avoid blocking the loop.

### Scan Result

The scan result is logged and cached in Redis, but **does not gate ad distribution**. Whether an ad is flagged or not, it is still stored and will be sent during partner rounds. This is intentional — moderation is informational only at this stage.

## Ping Stripping

Before storing the ad, all pings (`@everyone`, `@here`, `<@&...>`) are removed via `PING_RE`. The correct ping is re-added at send time by `parse_ping` based on the receiving server's config and the size-based ping tier.

## Storage

Cleaned ads stored at `ads:{guild_id}` with no TTL — overwritten each 3-hour cycle. If the cycle misses a guild (no ad found), the old ad remains in Redis and will continue to be used.

## Redis Pipeline Batching

Ads are written in batches of `cache.pipeline_batch` (250) using `redis.pipeline()` to avoid per-guild round-trips.

## Whitelisted Links

Managed via Postgres `whitelisted_links` table. On cog load, all links are copied to Redis set `whitelisted_links`. Whitelisted links are stripped from ad text before scanning and storage.

## Updating the Claude Cache Version

If `src/prompts.py` changes, the `claude_cache_version` in `config.yaml` must be bumped. Stale scan results keyed on the old version will continue to be served until they expire (30 days) unless the version is incremented.
