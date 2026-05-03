from discord.ext import tasks, commands
from src.checks import is_owner, has_management
from src.prompts import SCAN_PROMPT, RULE_PATTERNS
from anthropic import AsyncAnthropic
from redis.asyncio import Redis
from asyncpg import Pool
import discord, random, logging, asyncio, re, os, hashlib, json

LINK_REGEX = re.compile(r"https?://\S+")
PING_RE = re.compile(r"@everyone|@here|<@&\d+>")

logger = logging.getLogger(__name__)

class AddBotView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add WaveBot", style=discord.ButtonStyle.blurple, custom_id="wavebot:add_bot")
    async def add_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info("Add bot view clicked by user: %s guild: %s", interaction.user.name, interaction.guild.name)
        embed = discord.Embed(
            title="Add WaveBot to your server!",
            color=discord.Color.fuchsia()
        )
        embed.add_field(
            name="Invite the bot",
            value=f'[Click Here](https://discord.com/oauth2/authorize?client_id=1487962334138863666) and click "Add to server"',
            inline=False
        )
        embed.add_field(
            name="Grant permissions",
            value="The bot needs **Send Messages** and **Mention Everyone** permissions in both:\n"
                  "- Your **partner channel** (where ads are posted)\n"
                  "- Your **logging channel** (for errors, warnings, and announcements)",
            inline=False
        )
        embed.add_field(
            name="Configure the bot",
            value="Run `/setup` for a step-by-step interactive setup guide (recommended), or use `/config set` to configure manually",
            inline=False
        )
        embed.add_field(
            name="Join the support server",
            value="Click the link sent with this embed",
            inline=False
        )
        await interaction.response.send_message("https://discord.gg/uacMXzbAfg", embed=embed, ephemeral=True)

def get_req(count_a: int, count_b: int) -> dict:
    if count_a >= count_b:
        host, guest = count_a, count_b
        a_is_host = True
    else:
        host, guest = count_b, count_a
        a_is_host = False
    REF = 2300
    scale = host / REF
    tiers = [
        (round(400 * scale), "none"),
        (round(800 * scale), "partner"),
        (round(1700 * scale), "here"),
        (round(2000 * scale), "partnerhere"),
        (float("inf"), "member")
    ]
    ping_a, ping_b = "none", "none"

    for ceiling, host_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, "member"
            else:
                ping_a, ping_b = "member", host_ping
            logger.debug("scale: %.3f ceiling: %s -> host_ping: %s", scale, ceiling, host_ping)
            break

    result = {"server_a": ping_a, "server_b": ping_b, "host": "server_a" if a_is_host else "server_b"}
    return result

class Partner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis: Redis = bot.redis
        self.db_pool: Pool = bot.db_pool
        self._partner_lock = asyncio.Lock()
        self._scan_semaphore = asyncio.Semaphore(3)
        self.client: AsyncAnthropic = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    partnerGroup = discord.app_commands.Group(
        name="partner",
        description="Partner commands"
    )

    async def parse_ping(self, guild_id: int, ping: str = "none") -> str:
        config = await self.bot.config.get(guild_id)
        
        if ping == "member":
            return f"<@&{config.get('member_role')}>"
        
        elif ping == "partner":
            return f"<@&{config.get('partner_ping_role')}>"
        
        elif ping == "here":
            return "@here"
        
        elif ping == "partnerhere":
            return f"@here <@&{config.get('partner_ping_role')}>"
        else: # none
            return ""

    async def has_cooldown(self, a: int, b: int) -> bool:
        key = f"{self.bot.yaml_config['cache']['cache_version']}:partner_cooldown:{min(a,b)}:{max(a,b)}"
        result = bool(await self.redis.exists(key))
        logger.debug("%s -> %s", key, "HIT" if result else "MISS")
        return result

    async def set_cooldown(self, a: int, b: int):
        key = f"{self.bot.yaml_config['cache']['cache_version']}:partner_cooldown:{min(a,b)}:{max(a,b)}"
        await self.redis.set(key, 1, ex=self.bot.yaml_config['cache']['partner_cooldown'])
        logger.debug("SET %s (7d)", key)

    async def validate_server(self, guild: discord.Guild, config: dict | None = None) -> str | None:
        if config is None:
            config = await self.bot.config.get(guild.id)
        if not config:
            return "No configuration found"
        reqs = self.bot.yaml_config['requirements']

        member_role = guild.get_role(config.get("member_role"))
        partner_role = guild.get_role(config.get("partner_ping_role"))
        partner_channel = guild.get_channel(config.get("partner_channel"))

        if not member_role:
            return "Member role not configured"
        if not partner_role:
            return "Partner role not configured"
        if not partner_channel:
            return "Partner channel not configured"

        total = guild.member_count or 1
        min_member = reqs['member_role_min_coverage']
        min_visible = reqs['channel_visibility_min']
        min_partner = reqs['partner_role_min_coverage']

        member_pct = len(member_role.members) / total
        if member_pct < min_member:
            return f"Less than {round(min_member * 100)}% of server members have the member role, make sure your member role is assigned to everyone"

        if not partner_channel.permissions_for(member_role).view_channel:
            return f"Less than {round(min_visible * 100)}% of members can see the partner channel, make sure your partner channel is visible to everyone"

        partner_pct = len(partner_role.members) / total
        if partner_pct < min_partner:
            return f"Less than {round(min_partner * 100)}% of members have the partner ping role"

        return None

    async def match_servers(self, guilds: list[tuple[int, int]]) -> tuple[list[tuple[int, int]], list[int]]:
        logger.info("[match] starting with %d servers", len(guilds))
        pool = [id for id, _ in guilds]
        random.shuffle(pool)  # randomise before sort so ties break randomly

        if len(pool) < 2:
            return [], pool

        ver = self.bot.yaml_config['cache']['cache_version']
        all_pairs = [(min(a, b), max(a, b)) for i, a in enumerate(pool) for b in pool[i + 1:]]

        # Fetch all cooldowns in one pipeline round-trip instead of n²/2 individual calls
        async with self.redis.pipeline(transaction=False) as pipe:
            for a, b in all_pairs:
                pipe.exists(f"{ver}:partner_cooldown:{a}:{b}")
            results = await pipe.execute()

        on_cooldown = {pair for pair, hit in zip(all_pairs, results) if hit}
        logger.info("[match] cooldown check: %d/%d pairs blocked", len(on_cooldown), len(all_pairs))

        # Build adjacency sets
        neighbors: dict[int, set[int]] = {s: set() for s in pool}
        for a, b in all_pairs:
            if (a, b) not in on_cooldown:
                neighbors[a].add(b)
                neighbors[b].add(a)

        # Greedy maximum matching — most-constrained nodes first
        # Picking the partner with the fewest remaining options keeps the graph
        # denser for subsequent nodes, approaching optimal without Blossom complexity.
        order = sorted(pool, key=lambda x: len(neighbors[x]))
        matched: set[int] = set()
        pairs: list[tuple[int, int]] = []

        for server in order:
            if server in matched:
                continue
            available = [p for p in neighbors[server] if p not in matched]
            if not available:
                continue
            partner = min(available, key=lambda x: len(neighbors[x] - matched))
            pairs.append((server, partner))
            matched.add(server)
            matched.add(partner)

        sat_out = [s for s in pool if s not in matched]
        logger.info("result: %d pairs, %d sat out", len(pairs), len(sat_out))
        for a, b in pairs:
            logger.debug("paired %d <-> %d", a, b)
        for s in sat_out:
            logger.warning("sat out or all on cooldown: %d", s)
        return pairs, sat_out

    async def partner(self, server1_id: int, server2_id: int):
        logger.info("starting partner %d <-> %d", server1_id, server2_id)

        config1 = await self.bot.config.get(server1_id)
        config2 = await self.bot.config.get(server2_id)
        if not config1 or not config2:
            logger.warning("abort %d<->%d: missing config (config1=%s config2=%s)", server1_id, server2_id, bool(config1), bool(config2))
            return None, None

        guild1: discord.Guild = self.bot.get_guild(server1_id)
        guild2: discord.Guild = self.bot.get_guild(server2_id)
        if not guild1 or not guild2:
            logger.warning("abort %d<->%d: guild not in cache (guild1=%s guild2=%s)", server1_id, server2_id, bool(guild1), bool(guild2))
            return None, None

        logger.debug("guilds resolved: %s (%d members) <-> %s (%d members)", guild1.name, guild1.member_count, guild2.name, guild2.member_count)

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        channel2 = guild2.get_channel(config2.get("partner_channel"))
        if not channel1 or not channel2:
            logger.warning("abort %d<->%d: channel not found (ch1=%s ch2=%s)", server1_id, server2_id, bool(channel1), bool(channel2))
            return None, None
        logger.debug("channels resolved: #%s (%d) <-> #%s (%d)", getattr(channel1, 'name', None), server1_id, getattr(channel2, 'name', None), server2_id)

        r = get_req(guild1.member_count, guild2.member_count)
        logger.debug("%d(%d) pings %s | %d(%d) pings %s | host: %s", server1_id, guild1.member_count, r['server_a'], server2_id, guild2.member_count, r['server_b'], r['host'])

        raw_ad1 = await self.redis.get(f'ads:{server1_id}')
        raw_ad2 = await self.redis.get(f'ads:{server2_id}')
        if not raw_ad1 or not raw_ad2:
            logger.warning("abort %d<->%d: missing ad (ad1=%s ad2=%s)", server1_id, server2_id, bool(raw_ad1), bool(raw_ad2))
            return None, None

        ad1 = f"{raw_ad1}\n\n{await self.parse_ping(server2_id, r['server_b'])}"
        ad2 = f"{raw_ad2}\n\n{await self.parse_ping(server1_id, r['server_a'])}"

        logger.debug("ad lengths: server1_ad=%d server2_ad=%d (ad1 sent to ch2, ad2 sent to ch1)", len(ad1), len(ad2))
        if len(ad1) > 2000 or len(ad2) > 2000:
            logger.warning("abort: ad too long - server1_ad=%d server2_ad=%d (max 2000)", len(ad1), len(ad2))
            return None, None

        logger.debug("sending ad2 -> #%s in %s (%d)", channel1.name, guild1.name, server1_id)
        try:
            await channel1.send(ad2, view=AddBotView())
            logger.info("sent ad2 -> %d #%s OK", server1_id, channel1.name)
        except Exception as e:
            logger.error("failed sending to %d #%s: %s", server1_id, channel1.name, e)
            return None, None
        logger.debug("sending ad1 -> #%s in %s (%d)", channel2.name, guild2.name, server2_id)
        try:
            await channel2.send(ad1, view=AddBotView())
            logger.info("sent ad1 -> %d #%s OK", server2_id, channel2.name)
        except Exception as e:
            logger.error("failed sending to %d #%s: %s", server2_id, channel2.name, e)
            return None, None

        await self.set_cooldown(server1_id, server2_id)
        logger.debug("done %s (%d) <-> %s (%d)", guild1.name, server1_id, guild2.name, server2_id)
        return channel1, channel2

    async def scan_ad(self, ad: str) -> dict:
        hits = []
        lower = ad.lower()
        for rule, patterns in RULE_PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, lower):
                    hits.append(f"{rule}: {m.group()}")
        regex_hits = list(set(hits))
        if regex_hits:
            return {"sus": True, "confidence": 0.95, "ai_hits": [], "regex_hits": regex_hits, "user_reason": "Your ad was flagged during the regex prescan"}
        message = await self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0.1,
            system=[{"type": "text", "text": SCAN_PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[
                {"role": "user", "content": f"Advertisement:\n{ad}"},
                {"role": "assistant", "content": "{"},
            ],
        )
        try:
            raw = "{" + message.content[0].text.strip()
            result = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.error("failed to parse claude response for ad: %.100s", ad)
            result = {"sus": True, "confidence": 0.5, "ai_hits": [], "regex_hits": [], "user_reason": "Your ad could not be automatically verified. Please review the server rules and resubmit."}
        return result

    async def index_ad(self, guild_id: int) -> bool:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False
        config = await self.bot.config.get(guild_id)
        if not config:
            return False
        ad_channel = guild.get_channel(config.get("ad_channel"))
        if not ad_channel:
            return False
        whitelisted = await self.redis.smembers("whitelisted_links")
        async for message in ad_channel.history(limit=10):
            if LINK_REGEX.search(message.content):
                ad_message = message.content
                for link in whitelisted:
                    ad_message = ad_message.replace(link, "")
                ad_hash = hashlib.sha256(ad_message.encode()).hexdigest()[:12]
                ver = self.bot.yaml_config['cache']['claude_cache_version']
                cached = await self.redis.get(f"{ver}:claude:{ad_hash}")
                if not cached:
                    async with self._scan_semaphore:
                        try:
                            scan_result = await asyncio.wait_for(self.scan_ad(ad_message), timeout=30.0)
                        except asyncio.TimeoutError:
                            scan_result = {"sus": False, "confidence": 0.5, "ai_hits": [], "regex_hits": [], "user_reason": "Timed out"}
                        cached = json.dumps(scan_result, indent=2)
                        await self.redis.set(f"{ver}:claude:{ad_hash}", cached, ex=2592000)
                        await asyncio.sleep(self.bot.yaml_config['delays']['scan_ad'])
                logger.info("cached: %s scan result: %s", guild_id, cached)
                await self.redis.set(f"ads:{guild_id}", PING_RE.sub("", ad_message))
                return True
        return False

    async def index_ads(self) -> dict:
        whitelisted = await self.redis.smembers("whitelisted_links")
        missing_channel_embed = discord.Embed(title="Ad channel missing", description="Use `/config set` to set one", color=discord.Color.dark_red())
        missing_ad_embed = discord.Embed(title="Ad message missing", description="Your ad message was not found in the recent 10 messages in the channel", color=discord.Color.dark_red())
        pending = []
        summary = {"total": len(self.bot.guilds), "no_config": 0, "missing_channel": 0, "cached": 0, "missing_ad": 0}
        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            if not config:
                summary["no_config"] += 1
                continue
            ad_channel = guild.get_channel(config.get("ad_channel"))
            log_channel = guild.get_channel(config.get("log_channel"))
            if not ad_channel:
                summary["missing_channel"] += 1
                if log_channel:
                    try:
                        await log_channel.send(embed=missing_channel_embed)
                    except discord.HTTPException:
                        pass
                continue
            ad_message = None
            async for message in ad_channel.history(limit=10):
                if LINK_REGEX.search(message.content):
                    ad_message = message.content
                    for link in whitelisted:
                        ad_message = ad_message.replace(link, "")
                    ad_hash = hashlib.sha256(ad_message.encode()).hexdigest()[:12]
                    ver = self.bot.yaml_config['cache']['claude_cache_version']
                    cached = await self.redis.get(f"{ver}:claude:{ad_hash}")
                    if not cached:
                        async with self._scan_semaphore:
                            try:
                                scan_result = await asyncio.wait_for(self.scan_ad(ad_message), timeout=30.0)
                            except asyncio.TimeoutError:
                                scan_result = {"sus": False, "confidence": 0.5, "ai_hits": [], "regex_hits": [], "user_reason": "Timed out"}
                            cached = json.dumps(scan_result, indent=2)
                            await self.redis.set(f"{ver}:claude:{ad_hash}", cached, ex=2592000)
                            await asyncio.sleep(self.bot.yaml_config['delays']['scan_ad'])
                    logger.info("cached: %s scan result: %s", guild.id, cached)
                    break
            if ad_message:
                pending.append((f"ads:{guild.id}", PING_RE.sub("", ad_message)))
                summary["cached"] += 1
            else:
                summary["missing_ad"] += 1
                if log_channel:
                    try:
                        await log_channel.send(embed=missing_ad_embed)
                    except discord.HTTPException:
                        pass
            await asyncio.sleep(0)
        batch = self.bot.yaml_config['cache']['pipeline_batch']
        for i in range(0, max(len(pending), 1), batch):
            chunk = pending[i:i + batch]
            if not chunk:
                break
            async with self.redis.pipeline() as pipe:
                for key, value in chunk:
                    pipe.set(key, value)
                await pipe.execute()
            await asyncio.sleep(0)
        return summary

    async def cog_load(self):
        self.bot.add_view(AddBotView())
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT link FROM whitelisted_links")
        await self.redis.delete("whitelisted_links")
        if rows:
            await self.redis.sadd("whitelisted_links", *[r["link"] for r in rows])
        if self.bot.is_ready() and not self.partner_loop.is_running():
            logger.debug("bot already ready, starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("bot not ready yet, loop will start on_ready")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(AddBotView())
        if not self.partner_loop.is_running():
            logger.info("starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("partner_loop already running")

    async def _run_partner_round(self):
        await self.index_ads()
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id FROM blacklists")
            blacklisted_ids = {row[0] for row in rows}
        logger.debug("%d blacklisted guilds loaded", len(blacklisted_ids))

        available = []
        for guild in self.bot.guilds:
            if guild.id in blacklisted_ids:
                logger.debug("skip %s (%d): blacklisted", guild.name, guild.id)
                continue
            config = await self.bot.config.get(guild.id)
            if not config:
                continue

            partner_channel = guild.get_channel(config.get("partner_channel"))
            ad_channel = guild.get_channel(config.get("ad_channel"))
            member_role = guild.get_role(config.get("member_role"))
            partner_ping_role = guild.get_role(config.get("partner_ping_role"))

            missing = []
            if not partner_channel: missing.append("partner_channel")
            if not ad_channel: missing.append("ad_channel")
            if not member_role: missing.append("member_role")
            if not partner_ping_role: missing.append("partner_ping_role")
            if missing:
                logger.info("skip %s (%d): missing config — %s", guild.name, guild.id, ', '.join(missing))
                continue

            if not isinstance(partner_channel, discord.TextChannel):
                logger.info("skip %s (%d): partner_channel is wrong type", guild.name, guild.id)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Partner channel not found", description="Use `/config set` to set one", color=discord.Color.dark_red()))
                    except discord.HTTPException:
                        pass
                continue

            perms = partner_channel.permissions_for(guild.me)
            if not perms.send_messages or not perms.mention_everyone:
                logger.info("skip %s (%d): missing perms in #%s — send=%s mention=%s", guild.name, guild.id, partner_channel.name, perms.send_messages, perms.mention_everyone)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Missing permissions", description="I need `Send Messages` and `Mention Everyone` permissions in the partner channel", color=discord.Color.dark_red()))
                    except discord.HTTPException:
                        pass
                continue

            ad = await self.redis.get(f"ads:{guild.id}")
            if not ad:
                logger.info("skip %s (%d): no ad in redis", guild.name, guild.id)
                continue

            reason = await self.validate_server(guild, config)
            if reason:
                logger.info("skip %s (%d): validation failed — %s", guild.name, guild.id, reason)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Requirements not met", description=reason, color=discord.Color.dark_red()))
                    except discord.HTTPException:
                        pass
                continue

            logger.debug("eligible %s (%d) members=%d", guild.name, guild.id, guild.member_count)
            available.append((guild.id, guild.member_count))
            await asyncio.sleep(0)

        logger.info("%d eligible servers going into matching", len(available))
        available_map = {gid: mc for gid, mc in available}
        pairs, sat_out = await self.match_servers(available)

        if len(sat_out) >= 2:
            ver = self.bot.yaml_config['cache']['cache_version']
            sat_pairs = [(min(a, b), max(a, b)) for i, a in enumerate(sat_out) for b in sat_out[i + 1:]]
            if sat_pairs:
                async with self.redis.pipeline(transaction=False) as pipe:
                    for a, b in sat_pairs:
                        pipe.delete(f"{ver}:partner_cooldown:{a}:{b}")
                    await pipe.execute()
                logger.info("cleared %d cooldowns for %d sat-out servers, retrying match", len(sat_pairs), len(sat_out))
                retry_pairs, still_out = await self.match_servers([(s, available_map[s]) for s in sat_out])
                pairs.extend(retry_pairs)
                if still_out:
                    logger.warning("%d servers still unmatched after cooldown reset: %s", len(still_out), still_out)

        for a, b in pairs:
            guild_a = self.bot.get_guild(a)
            guild_b = self.bot.get_guild(b)
            logger.info("attempting pair: %s <-> %s", guild_a.name if guild_a else a, guild_b.name if guild_b else b)
            ch1, ch2 = await self.partner(a, b)
            await asyncio.sleep(self.bot.yaml_config['delays']['partner_pair'])
            if ch1:
                logger.debug("success: %s <-> %s", guild_a.name if guild_a else a, guild_b.name if guild_b else b)
            else:
                logger.warning("failed pair: %s <-> %s — see reason above", guild_a.name if guild_a else a, guild_b.name if guild_b else b)

    @tasks.loop(seconds=21600) # cant be in config
    async def partner_loop(self):
        logger.info("loop #%d fired", self.partner_loop.current_loop)
        if self._partner_lock.locked():
            logger.info("skipping — already running in this process")
            return
        async with self._partner_lock:
            acquired = await self.redis.set("last_partner_run", 1, nx=True, ex=self.bot.yaml_config['cache']['redis_lock'])
            if not acquired:
                logger.info("skipping — another instance already running (last_partner_run key exists)")
                return
            logger.debug("[loop] acquired lock, proceeding")
            await self._run_partner_round()

    @partner_loop.before_loop
    async def before_partner_loop(self):
        await self.bot.wait_until_ready()
        
    @partnerGroup.command(name="status", description="Check why your server may not be receiving partners")
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    @has_management()
    async def partner_status(self, interaction: discord.Interaction):
        guild = interaction.guild
        issues = []

        # Blacklist
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT reason FROM blacklists WHERE guild_id = $1", guild.id)
        if row:
            await interaction.response.send_message(
                f"This server is **blacklisted**.\nReason: {row['reason']}",
                ephemeral=True
            )
            return

        # Config
        config = await self.bot.config.get(guild.id)
        if not config:
            await interaction.response.send_message(
                "No configuration found. Run `/setup` to get started.",
                ephemeral=True
            )
            return

        # Resolve objects
        partner_channel = guild.get_channel(config.get("partner_channel")) if config.get("partner_channel") else None
        ad_channel = guild.get_channel(config.get("ad_channel")) if config.get("ad_channel") else None
        member_role = guild.get_role(config.get("member_role")) if config.get("member_role") else None
        partner_ping_role = guild.get_role(config.get("partner_ping_role")) if config.get("partner_ping_role") else None

        if not config.get("partner_channel"):
            issues.append("Partner channel not set, run `/config set`")
        elif not partner_channel:
            issues.append("Partner channel id is set but the channel no longer exists, update it with `/config set`")

        if not config.get("ad_channel"):
            issues.append("Ad channel not set, run `/config set`")
        elif not ad_channel:
            issues.append("Ad channel id is set but the channel no longer exists, update it with `/config set`")

        if not config.get("member_role"):
            issues.append("Member role not set, run `/config set`")
        elif not member_role:
            issues.append("Member role id is set but the role no longer exists, update it with `/config set`")

        if not config.get("partner_ping_role"):
            issues.append("Partner ping role not set, run `/config set`")
        elif not partner_ping_role:
            issues.append("Partner ping role id is set but the role no longer exists, update it with `/config set`")

        if not config.get("log_channel"):
            issues.append("Log channel not set (optional but extremely recommended), run `/config set`")

        # Channel type + perms
        if partner_channel:
            if not isinstance(partner_channel, discord.TextChannel):
                issues.append("Partner channel is not a text channel — select a standard text channel")
            else:
                perms = partner_channel.permissions_for(guild.me)
                if not perms.send_messages:
                    issues.append(f"Missing **Send Messages** permission in {partner_channel.mention}")
                if not perms.mention_everyone:
                    issues.append(f"Missing **Mention Everyone** permission in {partner_channel.mention}")

        # Ad in Redis
        ad = await self.redis.get(f"ads:{guild.id}")
        if not ad:
            if ad_channel:
                issues.append(f"No ad found in {ad_channel.mention}, post a message containing your `discord.gg` invite link")
            else:
                issues.append("No ad cached, set your ad channel and post a message with your `discord.gg` invite link")
        elif len(ad) > 2000:
            issues.append("Cached ad exceeds 2000 characters (discord imposed limit), shorten your ad message")

        if issues:
            lines = "\n".join(f"- {i}" for i in issues)
            embed = discord.Embed(
                title="Partner Status - Issues Found",
                description=lines,
                color=discord.Color.red()
            )
        else:
            embed = discord.Embed(
                title="Partner Status - Eligible",
                description="No issues found.",
                color=discord.Color.green()
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @partnerGroup.command(name="force")
    @is_owner()
    async def force_partner(self, interaction: discord.Interaction, server_id_1: str, server_id_2: str):
        logger.info("[force_partner] invoked by %d: %s <-> %s", interaction.user.id, server_id_1, server_id_2)
        await interaction.response.defer(ephemeral=True)
        if server_id_1 == server_id_2:
            logger.warning("[force_partner] rejected: same server id %s", server_id_1)
            await interaction.followup.send("Cannot partner a server with itself.", ephemeral=True)
            return
        try:
            channel1, channel2 = await self.partner(int(server_id_1), int(server_id_2))
        except Exception as e:
            logger.error("[force_partner] exception: %s", e, exc_info=True)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return
        if not channel1:
            logger.warning("[force_partner] partner() returned None for %s <-> %s", server_id_1, server_id_2)
            await interaction.followup.send("Failed - check logs and console for details.", ephemeral=True)
            return
        logger.info("[force_partner] SUCCESS: %s <-> %s", channel1, channel2)
        await interaction.followup.send(f"Partnered: {channel1.mention} | {channel2.mention}", ephemeral=True)

    @partnerGroup.command(name="loopinfo", description="Get info on the partner loop")
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    async def loop_info(self, interaction: discord.Interaction):
        loop = self.partner_loop

        if not loop.is_running():
            await interaction.response.send_message("`partner_loop` is not running.", ephemeral=True)
            return

        next_iter = loop.next_iteration

        embed = discord.Embed(title="Partner Loop Info", color=discord.Color.fuchsia())
        embed.add_field(name="Running", value=str(loop.is_running()), inline=True)
        embed.add_field(name="Failed", value=str(loop.failed()), inline=True)
        embed.add_field(name="Next Run", value=f"<t:{int(next_iter.timestamp())}:R>", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @partnerGroup.command(name="ad", description="Send a server's partner ad")
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    async def send_ad(self, interaction: discord.Interaction, guild_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.followup.send("Invalid guild id", ephemeral=True)
            return
        ad = await self.redis.get(f"ads:{gid}")
        if not ad:
            await self.index_ad(gid)
            ad = await self.redis.get(f"ads:{gid}")
        if not ad:
            await interaction.followup.send("No ad found for that server.", ephemeral=True)
            return
        await interaction.followup.send(ad, ephemeral=True)

    @partnerGroup.command(name="indexads", description="Re-index all server ads and show a summary")
    @is_owner()
    async def indexads(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        summary = await self.index_ads()
        embed = discord.Embed(title="Ad Index Summary", color=discord.Color.fuchsia())
        embed.add_field(name="Total Guilds", value=str(summary["total"]), inline=True)
        embed.add_field(name="Cached", value=str(summary["cached"]), inline=True)
        embed.add_field(name="Missing Ad", value=str(summary["missing_ad"]), inline=True)
        embed.add_field(name="Missing Channel", value=str(summary["missing_channel"]), inline=True)
        embed.add_field(name="No Config", value=str(summary["no_config"]), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @partnerGroup.command(name="loopforce")
    @is_owner()
    async def forceloop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self._partner_lock.locked():
            await interaction.followup.send("Already running, wait for it to finish.", ephemeral=True)
            return
        async with self._partner_lock:
            logger.info("[forceloop] force-acquired lock, proceeding")
            await self.redis.set("last_partner_run", 1, ex=self.bot.yaml_config['cache']['redis_lock'])
            await self._run_partner_round()
        await interaction.followup.send("Partner loop complete", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))