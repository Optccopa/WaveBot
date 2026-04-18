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

### 5. `NON_DISCORD_LINK` regex subdomain bypass
**Location:** `src/prompts.py:90`  
```python
r"https?://(?!discord\.gg|discord\.com|cdn\.discord)[^\s\)]+"
```
**Issue:** The negative lookahead checks whether the hostname *starts with* the allowed strings, not whether it equals them. `https://discord.gg.evil.com` starts with `discord.gg` so the lookahead fails — the URL is not flagged by regex and goes to AI scan instead.  
**Why it's bad:** Attacker can embed external links in an ad that bypass the regex pre-scan. Claude may or may not catch them.

---

## Low

### 8. `p!dr` prefix command is unauthenticated
**Location:** `main.py:199-201`  
**Issue:** Anyone in any server can run `p!dr` and get a reply. Reveals that the bot's prefix is `p!` and that the bot is responsive.  
**Why it's bad:** Information disclosure; low signal noise but confirms bot presence and prefix to anyone curious.

### 9. Duplicate `configmanager.py` — can silently diverge
**Location:** `src/configmanager.py`, `site/configmanager.py`  
**Issue:** Two identical copies of the file exist. No mechanism prevents them from drifting apart when one is updated.  
**Why it's bad:** A bug fix or schema change applied to one copy but not the other will cause the bot and web panel to behave differently — silently, with no import error.
