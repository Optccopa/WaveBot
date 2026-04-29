# Ad Scanning

## Overview

Ad scanning lives in `cogs/partner.py` (Partner cog). There is no dedicated scanning loop — ads are cached on demand when a guild's `ad_channel` is configured, and re-checked from Redis during partner rounds.

## Entry Points

| Caller | Function | When |
|--------|----------|------|
| `/config set` | `index_ad(guild_id)` | When `ad_channel` is in the updated fields |
| `/setup` confirm | `index_ad(guild_id)` | After full config is saved |
| `/partner ad` | `index_ad(guild_id)` | On cache miss before returning ad |
| `_run_partner_round()` | `index_ads()` | Start of every partner round (every 6h) |

`index_ads()` runs at the top of every partner round before eligibility checks, ensuring ads are fresh before matching. Also callable directly by owner tooling.

## Rate Limiting

`scan_ad()` calls are gated by `self._scan_semaphore` (`asyncio.Semaphore(3)`) — at most 3 concurrent Anthropic API calls across all entry points. The `asyncio.wait_for` timeout is applied inside the semaphore block so the 30s clock starts only after a slot is acquired.

After each scan (whether new or from `index_ads` loop), `asyncio.sleep(delays.scan_ad)` (default 1s) runs to pace sequential calls.

## Ad Discovery (`index_ad`)

For a single guild:

1. Resolves guild and config from Redis/Postgres
2. Gets `ad_channel` from config
3. Reads last 10 messages from `ad_channel`
4. Takes the first message matching `https?://\S+`
5. Strips whitelisted links (Redis set `whitelisted_links`)
6. Computes SHA-256 hash (first 12 chars) for scan cache keying
7. Scans via `scan_ad()` if not already cached
8. Strips pings via `PING_RE`, stores at `ads:{guild_id}` (no TTL)
9. Returns `True` if ad was stored, `False` if no ad found or channel missing

## Scanning Pipeline

### Step 1 — Regex Pre-scan

`RULE_PATTERNS` from `src/prompts.py` defines rule → pattern lists. If any pattern matches, the ad is flagged immediately with confidence 0.95 and the AI call is skipped.

### Step 2 — Claude Haiku

If regex passes, the ad is sent to `claude-haiku-4-5-20251001` with prompt caching (`cache_control: ephemeral` on system prompt). Model responds in JSON format (prefilled with `{` to force JSON output).

Scan cache key: `{claude_cache_version}:claude:{ad_hash}` — TTL 30 days. Results reused until ad content changes.

Timeout: 30 seconds via `asyncio.wait_for`. On timeout, `sus=False` confidence 0.5 is stored — ad passes through. This is a known gap (see AUDIT.md).

### Scan Result

Scan result is logged and cached but **does not gate ad distribution**. `sus: true` ads are still stored and sent during partner rounds. Moderation is informational only at this stage.

## Ping Stripping

Before storing, all pings (`@everyone`, `@here`, `<@&...>`) are removed via `PING_RE`. The correct ping is re-added at send time by `parse_ping` based on the receiving server's config and size-based ping tier.

## Storage

`ads:{guild_id}` — string, no TTL. Overwritten each time `index_ad` runs successfully. If a guild's ad channel has no qualifying message, the old cached ad remains and continues to be used in partner rounds.

## Bulk Indexing (`index_ads`)

`index_ads()` iterates all guilds, runs the same discovery pipeline, and writes ads via Redis pipeline batches (`cache.pipeline_batch`, default 250). Sends `"Ad channel missing"` or `"Ad message missing"` embeds to `log_channel` on failure. Not called automatically — can be invoked by owner tooling.

## Whitelisted Links

Managed via Postgres `whitelisted_links` table. On Partner cog load, all links are synced to Redis set `whitelisted_links`. Stripped from ad text before scanning and before storage. Owner commands in `cogs/owneronly.py` update both Postgres and Redis in sync.

## Updating the Claude Cache Version

If `src/prompts.py` changes, bump `claude_cache_version` in `config.yaml`. Stale scan results on the old version persist up to 30 days unless the version is incremented.
