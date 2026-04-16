# WaveBot Security Findings

Audit date: 2026-04-16  
Scope: `main.py`, `cogs/`, `src/`, `site/`

---

## Critical

### 1. `@everyone` pass-through in partner ads
**Location:** `cogs/cache_ads.py` (ad indexing), `cogs/partner.py:204` (ad send)  
**Issue:** The ad scanner has no rule that flags `@everyone` or `@here` in ad text. The bot explicitly requires and holds `mention_everyone` permission in every partner channel. Any server owner who posts an ad containing `@everyone` will cause the bot to send that text — and the resulting ping — in every server it gets partnered with.  
**Why it's bad:** Malicious server owner can mass-ping `@everyone` across all partner servers on the next loop cycle.

---
## Medium

### 3. Non-atomic rate limit — INCR/EXPIRE race
**Location:** `site/app.py:166-171`  
```python
count = await redis.incr(key)
if count == 1:
    await redis.expire(key, window)
```
**Issue:** If the key expires between `incr` and `expire`, the next `incr` creates a new key with no TTL and the window never closes. The key persists until a manual flush or restart.  
**Why it's bad:** Rate limiting silently stops working for affected users; repeated key expiry/creation cycles can permanently disable the limit.

### 4. CSRF logout — `GET /logout` with no token check
**Location:** `site/app.py:250-254`  
**Issue:** Logout is a `GET` request with no CSRF token. An image tag, redirect, or prefetch on any page can silently log a user out.  
**Why it's bad:** Any site can embed `<img src="https://panel/logout">` to invalidate active sessions. Not account-takeover, but disruptive and embarrassing.

### 5. `NON_DISCORD_LINK` regex subdomain bypass
**Location:** `src/prompts.py:90`  
```python
r"https?://(?!discord\.gg|discord\.com|cdn\.discord)[^\s\)]+"
```
**Issue:** The negative lookahead checks whether the hostname *starts with* the allowed strings, not whether it equals them. `https://discord.gg.evil.com` starts with `discord.gg` so the lookahead fails — the URL is not flagged by regex and goes to AI scan instead.  
**Why it's bad:** Attacker can embed external links in an ad that bypass the regex pre-scan. Claude may or may not catch them.

### 6. Session cookie missing `Secure` flag
**Location:** `site/app.py:416-418`  
**Issue:** `EncryptedCookieStorage` is created without `cookie_params={"secure": True}`. If a browser ever hits the panel over HTTP (before a Traefik redirect, or through a misconfigured proxy), the session cookie is transmitted in cleartext.  
**Why it's bad:** Session hijacking if any part of the request path is unencrypted.

### 7. Missing `Strict-Transport-Security` header
**Location:** `site/app.py:58-66` (security headers middleware)  
**Issue:** `HSTS` is not set. Even with Traefik enforcing HTTPS, browsers don't know to refuse HTTP connections proactively.  
**Why it's bad:** First visit over HTTP leaks the session cookie before the redirect; browsers won't upgrade to HTTPS automatically on subsequent visits without HSTS.

---

## Low

### 8. `p!dr` prefix command is unauthenticated
**Location:** `main.py:199-201`  
**Issue:** Anyone in any server can run `p!dr` and get a reply. Reveals that the bot's prefix is `p!` and that the bot is responsive.  
**Why it's bad:** Information disclosure; low signal noise but confirms bot presence and prefix to anyone curious.

### 9. Non-atomic `DEL` + `SADD` for `bot:guild_ids` on startup
**Location:** `main.py:131-133`  
**Issue:** `on_ready` deletes the set then immediately re-adds all guild IDs. In the gap between `DEL` and `SADD`, the web panel's fallback query `SELECT guild_id FROM guild_config` is used — which only returns servers that have a config row, excluding newly-joined servers with no config yet.  
**Why it's bad:** Under load, the web panel may briefly show fewer servers than the bot is actually in, causing confusion or missed configuration.

### 10. ConfigManager cache write-write race
**Location:** `src/configmanager.py:53-57`  
**Issue:** `set()` reads the current cache, merges the new fields, and writes back — without any lock. Two concurrent `set()` calls can both read the same stale version and the second write discards the first's changes.  
**Why it's bad:** Config fields can be silently lost if two admins save simultaneously. DB stays correct; only the Redis cache is wrong (self-heals in 30 days or on next DB miss).

### 11. Whitelist Redis set only appended on startup, never rebuilt from DB
**Location:** `cogs/cache_ads.py:146-148`  
**Issue:** `cog_load` calls `sadd("whitelisted_links", ...)` but never clears the set first. If a link was removed from the DB while the bot was running and then the bot restarts, the removed link remains in Redis because the startup code only adds, never reconciles.  
**Why it's bad:** A removed whitelist entry continues to suppress link content in ads after restart, potentially letting a previously-flagged link slip through scans.

### 12. Rate limiting only on `POST /server`, not on `GET` endpoints
**Location:** `site/app.py` — rate limit applied at line 351, absent from `handle_server_get`, `handle_guild_list`  
**Issue:** `GET /` re-fetches the Discord guilds API on every request (cached 5 min per user, but first hit is always an upstream call). No limit exists on how fast a user can hit these endpoints.  
**Why it's bad:** An authenticated user can repeatedly hammer `GET /` to exhaust the Discord API rate limit for the bot's OAuth token or cause elevated Redis/DB load.

### 13. Duplicate `configmanager.py` — can silently diverge
**Location:** `src/configmanager.py`, `site/configmanager.py`  
**Issue:** Two identical copies of the file exist. No mechanism prevents them from drifting apart when one is updated.  
**Why it's bad:** A bug fix or schema change applied to one copy but not the other will cause the bot and web panel to behave differently — silently, with no import error.
