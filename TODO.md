# TODO

Issues sorted by priority. Based on code audit cross-referenced against current codebase state.

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

## [HIGH] Flagged ads still cached and sent to partners

**File:** [cogs/cache_ads.py:110-125](cogs/cache_ads.py#L110)

**Description**
```python
cached = await self.redis.get(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}")
if not cached:
    scan_result = await asyncio.wait_for(self.scan_ad(ad_message), timeout=30.0)
    ...
log.info("[cache_ads] guild %s scan result: %s", guild.id, response)  # only logged
break

if ad_message:
    pending.append((f"ads:{guild.id}", ad_message))  # always queued regardless of sus flag
```
`scan_result["sus"]` is logged but never acted upon. Every ad — even `"sus": true, "confidence": 0.95` — gets written to Redis and goes through partner rounds.

**Fix**
```python
result = json.loads(response)
if result.get("sus"):
    log.warning("[cache_ads] guild %s REJECTED ad: %s", guild.id, result.get("user_reason"))
    if log_channel:
        await log_channel.send(embed=discord.Embed(
            title="Ad rejected",
            description=result["user_reason"],
            color=discord.Color.dark_red()
        ))
    continue  # don't add to pending
```

---

## [HIGH] Whitelisted links stripped from ad before storing in Redis

**File:** [cogs/cache_ads.py:106-108](cogs/cache_ads.py#L106)

**Description**
```python
for link in whitelisted:
    ad_message = ad_message.replace(link, "")  # mutates ad_message in-place
...
pending.append((f"ads:{guild.id}", ad_message))  # stores the stripped version
```
`ad_message` is modified before being appended to `pending`, so the ad partners receive has holes where the whitelisted links were. Stripping was only meant for the scan input.

**Fix**
```python
ad_message = message.content
scan_input = ad_message
for link in whitelisted:
    scan_input = scan_input.replace(link, "")
ad_hash = hashlib.sha256(scan_input.encode()).hexdigest()[:12]
# pass scan_input to scan_ad, store original ad_message in pending
```

---

## [HIGH] `partner_loop` Redis dedup lock TTL shorter than loop interval

**File:** [cogs/partner.py:259-261](cogs/partner.py#L259)

**Description**
```python
@tasks.loop(seconds=21600)  # 6 hours
async def partner_loop(self):
    if not await self.redis.set("last_partner_run", 1, nx=True, ex=10800):  # 3 hour TTL
```
The dedup lock expires after 3h but the loop fires every 6h. If a shard reconnects or the container restarts, the loop task restarts immediately and can acquire the expired lock within the 3h–6h window, running a second partner round in the same cycle.

**Fix**
Set `ex=21600` (match loop interval) or `ex=18000` (5h — safely inside the window).

---

## [MEDIUM] `index_ads` has no per-guild exception isolation

**File:** [cogs/cache_ads.py:86](cogs/cache_ads.py#L86)

**Description**
The outer `for guild in self.bot.guilds` loop has no `try/except`. A single `discord.Forbidden` on `channel.history()` or a network timeout will propagate and abort the entire indexing run — all subsequent guilds get skipped silently.

**Fix**
```python
for guild in self.bot.guilds:
    try:
        ...
    except Exception as e:
        log.error("[cache_ads] guild %s indexing failed: %s", guild.id, e)
        continue
```

---

## [MEDIUM] `guild.member_count` can be `None` passed into `get_req()`

**File:** [cogs/partner.py:189](cogs/partner.py#L189)

**Description**
```python
r = get_req(guild1.member_count, guild2.member_count)
```
`guild.member_count` returns `None` when the guild isn't fully chunked. `get_req` immediately does `if count_a >= count_b` which raises `TypeError`. `check_partner_requirements` guards with `guild.member_count or 1` but `partner()` does not.

**Fix**
```python
r = get_req(guild1.member_count or 0, guild2.member_count or 0)
```

---

## [MEDIUM] `WebhookHandler` creates a new `aiohttp.ClientSession` per log message

**File:** [main.py:30-34](main.py#L30)

**Description**
```python
async def _send(self, msg: str):
    async with aiohttp.ClientSession() as session:  # new session every log line
        await session.post(...)
```
Under high log volume (e.g., a crashing partner loop) this creates hundreds of sessions rapidly, leaking file descriptors if any are cancelled mid-send.

**Fix**
Create one `aiohttp.ClientSession` at handler init and reuse it. Close it in `bot.close()`.

---

## [MEDIUM] `partner_loop` silently dies on unhandled exception

**File:** [cogs/partner.py:259](cogs/partner.py#L259)

**Description**
`tasks.loop` stops running if an exception escapes the loop body. There is no `@partner_loop.error` handler, so a crash kills all future partner rounds with no alert beyond a single log line.

**Fix**
```python
@partner_loop.error
async def partner_loop_error(self, error: Exception):
    logger.error("[partner_loop] crashed: %s", error, exc_info=True)
    self.partner_loop.restart()
```

---

## [MEDIUM] `AddBotView` registered twice as persistent view on startup

**File:** [cogs/partner.py:248-257](cogs/partner.py#L248)

**Description**
```python
async def cog_load(self):
    self.bot.add_view(AddBotView())   # registered here

async def on_ready(self):
    self.bot.add_view(AddBotView())   # and again here
```
On normal startup `on_ready` fires after `cog_load`, registering the view twice. Discord.py's persistent view dispatch routes the button callback to both instances, firing it twice per click.

**Fix**
Remove the `add_view` call from `on_ready`; `cog_load` is sufficient.

---

## [LOW] `/config set` uses raw `channel` object instead of computed `mention`

**File:** [cogs/config.py:61-68](cogs/config.py#L61)

**Description**
```python
channel = interaction.guild.get_channel(config.get('log_channel'))
if channel: mention = channel.mention
else: mention = "<Unconfigured>"

await interaction.response.send_message(
    f"...Watch {channel} for info...",  # `mention` computed but never used
```
When `channel` is `None` the message reads `Watch None for info`. When it exists it renders the raw `<TextChannel>` repr instead of a clickable mention.

**Fix** — change `{channel}` to `{mention}` in the f-string.

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
