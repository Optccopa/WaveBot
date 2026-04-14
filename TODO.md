except log channel perms

# TODO

Issues sorted by priority. Based on code audit cross-referenced against current codebase state.

---

## [HIGH] `whitelisted_links` Redis set not synced from Postgres on startup

**File:** [cogs/cache_ads.py:140](cogs/cache_ads.py#L140)

**Description**
`cog_load` only starts the loop — it never seeds `whitelisted_links` from Postgres. After any Redis flush or restart, `index_ads` reads an empty set and no links are filtered from ads until `addWhitelist` is called again.

**Fix**
```python
async def cog_load(self):
    async with self.bot.db_pool.acquire() as conn:
        rows = await conn.fetch("SELECT link FROM whitelisted_links")
    if rows:
        await self.redis.sadd("whitelisted_links", *[r["link"] for r in rows])
    if self.bot.is_ready() and not self.ad_loop.is_running():
        self.ad_loop.start()
```

---

## [MEDIUM] `(Testing Placeholder)` in production partner ads

**File:** [cogs/partner.py:211-212](cogs/partner.py#L211)

**Description**
```python
ad1 = f"{raw_ad1}\n\n{r['server_b']} (Testing Placeholder)"
ad2 = f"{raw_ad2}\n\n{r['server_a']} (Testing Placeholder)"
```
`r['server_b']` / `r['server_a']` are tier label strings (`"none"`, `"partner"`, `"here"`, `"member"`) — not Discord mentions. Partner channels receive ads with a footer like `member (Testing Placeholder)` instead of an actual role ping.

**Fix**
```python
def resolve_ping(guild: discord.Guild, config: dict, tier: str) -> str:
    if tier == "none":
        return ""
    if tier in ("here", "partnerhere"):
        return "@here"
    if tier == "partner":
        role = guild.get_role(config.get("partner_ping_role"))
    else:  # member
        role = guild.get_role(config.get("member_role"))
    return role.mention if role else ""

ping1 = resolve_ping(guild1, config1, r["server_a"])
ping2 = resolve_ping(guild2, config2, r["server_b"])
ad1 = f"{raw_ad1}\n\n{ping2}".strip()
ad2 = f"{raw_ad2}\n\n{ping1}".strip()
```

---

## [LOW] Setup wizard views missing `interaction_check`

**File:** [cogs/setup.py](cogs/setup.py) — all View subclasses

**Description**
None of the `discord.ui.View` subclasses implement `interaction_check`. Ephemeral messages currently prevent other users from seeing or clicking them, but no code-level guard exists. Any user who somehow interacts could advance another user's setup flow.

**Fix**
Pass `original_user` into each view and add:
```python
async def interaction_check(self, interaction: discord.Interaction) -> bool:
    return interaction.user == self.original_user
```
