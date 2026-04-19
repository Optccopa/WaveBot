# WaveBot Code Audit
_Generated: 2026-04-18_

---

## CRITICAL

### 1. @everyone/@here ping scan gap
**File:** `cogs/cache_ads.py:112,124`

`scan_ad()` is called on `ad_message` which still contains raw pings. `SCAN_PROMPT` has no rule flagging `@everyone`/`@here` in ad text, so ping-containing ads pass with `sus: false`. Pings are stripped at line 124 before Redis storage, so they won't be delivered — but the server owner is never flagged or penalized for the attempt. Bot holds `mention_everyone` permission in every partner channel. If `PING_RE` ever misses a format variant, delivery becomes possible.

**Impact:** Repeat abuse undetected; single regex gap away from mass-ping across entire partner network.

---

### 2. No cooldown set on half-send failure
**File:** `cogs/partner.py:284-298`

`channel1.send(ad2)` succeeds. `channel2.send(ad1)` raises. Function returns `None, None`. `set_cooldown()` (line 298) is never called. Server1 received Server2's ad; neither server is on cooldown. Next round they are eligible again — Server1 gets Server2's ad a second time.

**Impact:** Duplicate ad delivery; no half-success tracking or rollback path.

---

## HIGH

### 3. Duplicate ConfigManager implementations diverged
**File:** `src/configmanager.py` vs `site/configmanager.py`

Two separate copies with different cache invalidation behavior. `src` version deletes key then re-reads from DB. `site` version has its own logic. No mechanism prevents further drift. Fixes applied to one silently miss the other.

**Impact:** Cache/DB consistency bugs between bot and web panel; silent divergence.

---

### 4. N+1 Redis config reads in partner loop
**File:** `cogs/partner.py:330`

`await self.bot.config.get(guild.id)` called once per guild in a for loop. 1000 guilds = 1000 sequential Redis round-trips. No pipeline or batch pre-fetch before the loop.

**Fix:** Batch all guild IDs through a Redis pipeline before the loop; populate a local dict.

---

### 5. N+1 Redis config reads in ad loop
**File:** `cogs/cache_ads.py:86`

Same pattern as above. `await self.bot.config.get(guild.id)` per guild in `index_ads()`.

**Fix:** Same batch pre-fetch approach.

---

### 6. `bot:guild_info` Redis hash has no TTL
**File:** `main.py:165`

`hset("bot:guild_info", ...)` is called with no `ex`. Hash grows unbounded. Guilds that leave are removed via `hdel` in `on_guild_remove`, but name/icon/member_count fields go stale between bot restarts with no scheduled refresh.

**Impact:** Redis memory leak; web panel shows stale member counts.

---

### 7. `IndexError` uncaught in Claude response parse
**File:** `cogs/partner.py`, `scan_ad()`

`message.content[0].text` — if Anthropic returns an empty `content` list, this raises `IndexError`. The `except` on line 54 only catches `json.JSONDecodeError`. Unhandled `IndexError` propagates up, breaking the entire `index_ads()` loop for all subsequent guilds.

**Impact:** Single malformed API response halts ad indexing for all guilds that round.

---

## MEDIUM

### 8. `check_partner_requirements` is dead code
**File:** `cogs/partner.py:44-77`

`return True, None` on line 45 makes all validation below unreachable. Function is never called anywhere in the codebase. `validate_server()` handles actual checks.

**Impact:** Misleading code; dead validation logic may confuse future changes.

---

### 9. Blacklisted guilds remain in `bot:guild_ids`
**File:** `main.py` / `cogs/owneronly.py`

`bot:guild_ids` is not purged when a guild is blacklisted and the bot leaves it. Redis set still contains the guild ID. Web panel uses `bot:guild_ids` to display bot-present servers, so blacklisted guilds appear as active.

**Impact:** Site UI shows blacklisted guilds as valid bot members.

---

### 10. Validation fails open when bot is unreachable
**File:** `site/app.py:401-413`

`try/except Exception: pass` around the internal HTTP validation call silently swallows all errors. If the bot is down, config is saved without validation. Intentional for resilience, but invalid configs (wrong role IDs, closed channels) can be persisted.

**Impact:** Invalid server configs saved during bot downtime.

---

### 11. Claude parse failure returns ambiguous `sus: true`
**File:** `cogs/cache_ads.py:54-56`

`json.JSONDecodeError` fallback sets `sus: True, confidence: 0.5`. Indistinguishable in logs from a genuine moderate-confidence flag. Parse failures look like suspicious ads.

**Impact:** False positives in scan logs; operators cannot distinguish scan failure from real flags.

---

### 12. `guild_info` member count stale between restarts
**File:** `main.py:165-172`

`guild.member_count` is accurate at `on_ready` time but `bot:guild_info` hash is never updated after that (joins/leaves don't update the count field). Web panel displays stale counts.

**Impact:** Stale member counts in panel for long-running bot instances.

---

## LOW

### 13. Full scan JSON logged per ad
**File:** `cogs/cache_ads.py:120`

`log.info("... scan result: %s", ..., response)` dumps the full JSON response for every ad every 3 hours. High log volume at scale.

---

### 14. Partner loop interval hardcoded
**File:** `cogs/partner.py:416`

`@tasks.loop(seconds=21600)` requires a literal. Cannot be changed from `config.yaml` without a code edit and redeploy.

---

### 15. Hardcoded client ID and invite links
**File:** `cogs/partner.py:22` | `main.py:222`

`client_id=1487962334138863666` and `discord.gg/uacMXzbAfg` hardcoded in source. Should use `bot.user.id` and `config.yaml` respectively.

---

### 16. `set_cooldown` comment says "7d", config is 3d
**File:** `cogs/partner.py:148`

`logger.debug("[cooldown] SET %s (7d)", key)` — `partner_cooldown_ttl` in `config.yaml` is `259200` seconds = 3 days, not 7.

---

### 17. Webhook queue silently drops at capacity
**File:** `main.py:30-31`

`asyncio.QueueFull` is caught and passed with no log. During high-traffic periods, log messages are silently dropped with no indication.

---

### 18. Missing env var raises cryptic `KeyError` at startup
**File:** `site/app.py:185,224,443,462`

`os.environ["KEY"]` raises `KeyError` for missing vars. No startup validation with a clear error message listing which vars are required.

---

## Summary

| Severity | Count |
|----------|-------|
| Critical | 2     |
| High     | 5     |
| Medium   | 5     |
| Low      | 6     |

**Top priorities:** Close the @everyone scan gap, add IndexError catch in Claude response parsing, fix N+1 config reads, set cooldown on half-send failure.
