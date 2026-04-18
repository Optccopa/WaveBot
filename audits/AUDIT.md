# WaveBot Code Audit
_Generated: 2026-04-16_

---

## CRITICAL

### 1. @everyone/@here ping bypass in partner ads
**File:** `cogs/cache_ads.py:124`

Pings stripped AFTER Claude scans the ad. Scanner has no rule flagging `@everyone`/`@here` in ad text. Malicious server owner can post ads with mass pings, pass scan, get stripped before Redis storage — but bot holds `mention_everyone` permission (`setup.py:61`). Crafted ads can mass-ping all partner servers.

**Impact:** Mass-ping attack across entire partner network.

---

### 5. Duplicate configmanager diverged between bot and site
**File:** `src/configmanager.py` vs `site/configmanager.py`

Two copies already diverged in behavior:
- `src` (lines 53-55): Invalidates cache, re-reads from DB
- `site` (lines 53-57): Updates local copy, re-caches in Redis

No mechanism prevents further drift. Bug fixes applied to one silently miss the other.

**Impact:** Data consistency issues between bot and web panel.

---

### 6. No timeout on aiohttp ClientSession in site
**File:** `site/app.py:419`

`aiohttp.ClientSession()` created without timeout. Discord API calls in `_discord_get()` can hang indefinitely.

**Impact:** Resource exhaustion, hanging requests, potential DoS if Discord is unresponsive.

---

### 7. Missing variable assignment bug in config view
**File:** `cogs/config.py:62`

`if channel: channel.mention` evaluates but doesn't assign. `channel` remains a Channel object, not a mention string. Output shows object instead of `#channel-name`.

**Impact:** Malformed output in config update response shown to users.

---

### 9. Silent exception swallowing in WebhookHandler
**File:** `main.py:28-29,34-35`

Empty `except Exception: pass` blocks swallow all webhook logging errors. Failed logs are invisible.

**Impact:** No visibility into logging pipeline failures.

---

### 11. Missing env var validation in site app
**File:** `site/app.py:185-186,225`

Required env vars accessed with `os.environ["KEY"]` — missing vars cause cryptic `KeyError` at startup instead of clear startup error.

---

### 12. N+1 config queries in cache_ads loop
**File:** `cogs/cache_ads.py:85-86`

Individual Redis/DB config query per guild in loop. 1000 guilds = 1000 queries per loop run.

**Fix:** Batch load all guild configs before loop.

---

### 13. N+1 config queries in partner loop
**File:** `cogs/partner.py:276-280`

Same N+1 pattern as above in partner matching loop.

---

## LOW

### 14. Verbose logging of full ad content
**File:** `cogs/cache_ads.py:120`

Full JSON scan response logged for every ad. High volume = large logs.

---

### 15. Hardcoded loop interval for partner matching
**File:** `cogs/partner.py:262`

`@tasks.loop(seconds=21600)` hardcoded. Requires code change + redeploy to adjust.

---

### 16. JSON parse error defaults to ambiguous result
**File:** `cogs/cache_ads.py:54`

Malformed Claude response marks ad `sus: True` with confidence `0.5` — a guess rather than a real error state. Hard to distinguish genuine "sus" from parse failure in logs.

---

### 17. Hardcoded Discord invite links and IDs in source
**File:** `main.py:170,193` | `cogs/partner.py:22,42`

`discord.gg/uacMXzbAfg`, client ID `1487962334138863666`, channel IDs hardcoded. Should be in `config.yaml`.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 4 |
| Medium | 6 |
| Low | 4 |

**Top priorities:** Fix hardcoded DB password, re-enable partner validation, close @everyone ping gap.
