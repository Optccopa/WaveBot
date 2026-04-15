from discord.ext import tasks, commands
from src.checks import is_owner
from redis.asyncio import Redis
from asyncpg import Pool
import discord, random, logging

COOLDOWN_REDIS_VER = "v1"

logger = logging.getLogger(__name__)

class AddBotView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add WaveBot", style=discord.ButtonStyle.blurple, custom_id="wavebot:add_bot")
    async def add_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        logger.info("[AddBotView] button clicked by user=%d guild=%s", interaction.user.id, interaction.guild_id)
        embed = discord.Embed(
            title="Add WaveBot to your server!",
            color=discord.Color.fuchsia()
        )
        embed.add_field(
            name="Invite the bot",
            value='[Click Here](https://discord.com/oauth2/authorize?client_id=1487962334138863666) and click "Add to server"',
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

async def check_partner_requirements(guild: discord.Guild, channel: discord.TextChannel, config):
    return True, None # doesnt check them
    logger.debug("[req] checking %s (%d) channel=#%s", guild.name, guild.id, channel.name)
    member_role  = guild.get_role(config.get("member_role"))
    partner_role = guild.get_role(config.get("partner_ping_role"))

    if not member_role:
        logger.debug("[req] %d: member_role id=%s not found in guild", guild.id, config.get("member_role"))
        return False, "Member role not configured"
    if not partner_role:
        logger.debug("[req] %d: partner_ping_role id=%s not found in guild", guild.id, config.get("partner_ping_role"))
        return False, "Partner role not configured"

    total = guild.member_count or 1
    member_pct = len(member_role.members) / total
    logger.debug("[req] %d: member_role coverage %.1f%% (%d/%d)", guild.id, member_pct * 100, len(member_role.members), total)

    if member_pct < 0.85:
        return False, "Less than 85% of server members have the member role, Make sure your member role is assigned to everyone"

    role_members = member_role.members
    visible = sum(1 for m in role_members if channel.permissions_for(m).view_channel)
    visible_pct = visible / len(role_members) if role_members else 1.0
    logger.debug("[req] %d: channel visibility %.1f%% (%d/%d can see #%s)", guild.id, visible_pct * 100, visible, len(role_members), channel.name)
    if role_members and visible_pct < 0.95:
        return False, "Less than 95% of members can see the partner channel, Make sure your partner channel is visible to everyone"

    partner_pct = len(partner_role.members) / total
    logger.debug("[req] %d: partner_ping_role coverage %.1f%% (%d/%d)", guild.id, partner_pct * 100, len(partner_role.members), total)
    if partner_pct < 0.08:
        return False, "Less than 8% of members have partner ping role"

    logger.debug("[req] %d: all checks passed", guild.id)
    return True, None
 
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
            logger.debug("[get_req] host=%d guest=%d scale=%.3f ceiling=%s -> host_ping=%s", host, guest, scale, ceiling, host_ping)
            break

    result = {"server_a": ping_a, "server_b": ping_b, "host": "server_a" if a_is_host else "server_b"}
    logger.debug("[get_req] a=%d(%s) b=%d(%s) host=%s", count_a, ping_a, count_b, ping_b, result["host"])
    return result

class Partner(commands.Cog):
    def __init__(self, bot): 
        self.bot = bot
        self.redis: Redis = bot.redis
        self.db_pool: Pool = bot.db_pool

    partnerGroup = discord.app_commands.Group(
        name="partner",
        description="Partner commands"
    )

    async def has_cooldown(self, a: int, b: int) -> bool:
        key = f"{COOLDOWN_REDIS_VER}:partner_cooldown:{min(a,b)}:{max(a,b)}"
        result = bool(await self.redis.exists(key))
        logger.debug("[cooldown] %s -> %s", key, "HIT" if result else "MISS")
        return result

    async def set_cooldown(self, a: int, b: int):
        key = f"{COOLDOWN_REDIS_VER}:partner_cooldown:{min(a,b)}:{max(a,b)}"
        await self.redis.set(key, 1, ex=60 * 60 * 24 * 7)
        logger.debug("[cooldown] SET %s (7d)", key)

    async def match_servers(self, guilds: list[tuple[int, int]]) -> list[tuple[int, int]]:
        logger.info("[match] starting with %d servers", len(guilds))
        pool = [id for id, _ in guilds]
        random.shuffle(pool)
        pairs = []
        used = set()
        for server in pool:
            if server in used:
                continue
            candidates = [s for s in pool if s != server and s not in used]
            random.shuffle(candidates)
            matched = False
            for candidate in candidates:
                if not await self.has_cooldown(server, candidate):
                    pairs.append((server, candidate))
                    used.update([server, candidate])
                    logger.debug("[match] paired %d <-> %d", server, candidate)
                    matched = True
                    break
            if not matched:
                logger.warning("[match] no valid partner found for %s (all on cooldown or exhausted)", server)
        logger.info("[match] result: %d pairs", len(pairs))
        return pairs

    async def partner(self, server1_id: int, server2_id: int):
        logger.info("[partner] START %d <-> %d", server1_id, server2_id)

        config1 = await self.bot.config.get(server1_id)
        config2 = await self.bot.config.get(server2_id)
        if not config1 or not config2:
            logger.warning("[partner] ABORT %d<->%d: missing config (config1=%s config2=%s)", server1_id, server2_id, bool(config1), bool(config2))
            return None, None

        guild1 = self.bot.get_guild(server1_id)
        guild2 = self.bot.get_guild(server2_id)
        if not guild1 or not guild2:
            logger.warning("[partner] ABORT %d<->%d: guild not in cache (guild1=%s guild2=%s)", server1_id, server2_id, bool(guild1), bool(guild2))
            return None, None

        logger.debug("[partner] guilds resolved: %s (%d members) <-> %s (%d members)", guild1.name, guild1.member_count, guild2.name, guild2.member_count)

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        channel2 = guild2.get_channel(config2.get("partner_channel"))
        logger.debug("[partner] channels resolved: #%s (%d) <-> #%s (%d)", getattr(channel1, 'name', None), server1_id, getattr(channel2, 'name', None), server2_id)

        r = get_req(guild1.member_count, guild2.member_count)
        logger.info("[partner] %d(%d) pings %s | %d(%d) pings %s | host: %s", server1_id, guild1.member_count, r['server_a'], server2_id, guild2.member_count, r['server_b'], r['host'])

        raw_ad1 = await self.redis.get(f'ads:{server1_id}')
        raw_ad2 = await self.redis.get(f'ads:{server2_id}')
        
        ad1 = f"{raw_ad1}\n\n{r['server_b']} (Testing Placeholder)"
        ad2 = f"{raw_ad2}\n\n{r['server_a']} (Testing Placeholder)"

        logger.debug("[partner] ad lengths: server1_ad=%d server2_ad=%d (ad1 sent to ch2, ad2 sent to ch1)", len(ad1), len(ad2))
        if len(ad1) > 2000 or len(ad2) > 2000:
            logger.warning("[partner] ABORT: ad too long — server1_ad=%d server2_ad=%d (max 2000)", len(ad1), len(ad2))
            return None, None

        logger.info("[partner] sending ad2 -> #%s in %s (%d)", channel1.name, guild1.name, server1_id)
        try:
            await channel1.send(ad2, view=AddBotView())
            logger.info("[partner] sent ad2 -> %d #%s OK", server1_id, channel1.name)
        except Exception as e:
            logger.error("[partner] FAILED sending to %d #%s: %s", server1_id, channel1.name, e)
            return None, None
        logger.info("[partner] sending ad1 -> #%s in %s (%d)", channel2.name, guild2.name, server2_id)
        try:
            await channel2.send(ad1, view=AddBotView())
            logger.info("[partner] sent ad1 -> %d #%s OK", server2_id, channel2.name)
        except Exception as e:
            logger.error("[partner] FAILED sending to %d #%s: %s", server2_id, channel2.name, e)
            return None, None

        await self.set_cooldown(server1_id, server2_id)
        logger.info("[partner] DONE %s (%d) <-> %s (%d)", guild1.name, server1_id, guild2.name, server2_id)
        return channel1, channel2

    async def cog_load(self):
        self.bot.add_view(AddBotView())
        if self.bot.is_ready() and not self.partner_loop.is_running():
            logger.info("[cog_load] bot already ready, starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("[cog_load] bot not ready yet, loop will start on_ready")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(AddBotView())
        if not self.partner_loop.is_running():
            logger.info("[on_ready] starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("[on_ready] partner_loop already running")

    @tasks.loop(seconds=21600)
    async def partner_loop(self):
        logger.info("[loop] tick #%d fired", self.partner_loop.current_loop)
        acquired = await self.redis.set("last_partner_run", 1, nx=True, ex=10800)
        if not acquired:
            logger.info("[loop] skipping — another instance already running (last_partner_run key exists)")
            return
        logger.info("[loop] acquired lock, proceeding")
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id FROM blacklists")
            blacklisted_ids = {row[0] for row in rows}
        logger.info("[loop] %d blacklisted guilds loaded", len(blacklisted_ids))

        available = []
        for guild in self.bot.guilds:
            if guild.id in blacklisted_ids:
                logger.info("[loop] SKIP %s (%d): blacklisted", guild.name, guild.id)
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
                logger.info("[loop] SKIP %s (%d): missing config — %s", guild.name, guild.id, ', '.join(missing))
                continue

            if not isinstance(partner_channel, discord.TextChannel):
                logger.info("[loop] SKIP %s (%d): partner_channel is wrong type", guild.name, guild.id)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Partner channel not found", description="Use `/config set` to set one", color=discord.Color.dark_red()))
                    except discord.Forbidden:
                        pass
                continue

            perms = partner_channel.permissions_for(guild.me)
            if not perms.send_messages or not perms.mention_everyone:
                logger.info("[loop] SKIP %s (%d): missing perms in #%s — send=%s mention=%s", guild.name, guild.id, partner_channel.name, perms.send_messages, perms.mention_everyone)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Missing permissions", description="I need `Send Messages` and `Mention Everyone` permissions in the partner channel", color=discord.Color.dark_red()))
                    except discord.Forbidden:
                        pass
                continue 

            ad = await self.redis.get(f"ads:{guild.id}")
            if not ad:
                logger.info("[loop] SKIP %s (%d): no ad in redis", guild.name, guild.id)
                continue

            passed, reason = await check_partner_requirements(guild, partner_channel, config)
            if not passed:
                logger.info("[loop] SKIP %s (%d): req failed — %s", guild.name, guild.id, reason)
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel:
                    try:
                        await log_channel.send(embed=discord.Embed(title="Requirements not met", description=reason, color=discord.Color.dark_red()))
                    except discord.Forbidden:
                        pass
                continue

            logger.info("[loop] ELIGIBLE %s (%d) members=%d", guild.name, guild.id, guild.member_count)
            available.append((guild.id, guild.member_count))

        logger.info("[loop] %d eligible servers going into matching", len(available))
        pairs = await self.match_servers(available)

        for a, b in pairs:
            guild_a = self.bot.get_guild(a)
            guild_b = self.bot.get_guild(b)
            logger.info("[loop] attempting pair: %s <-> %s", guild_a.name if guild_a else a, guild_b.name if guild_b else b)
            ch1, ch2 = await self.partner(a, b)
            if ch1:
                logger.info("[loop] SUCCESS: %s <-> %s", guild_a.name if guild_a else a, guild_b.name if guild_b else b)
            else:
                logger.warning("[loop] FAILED pair: %s <-> %s — see reason above", guild_a.name if guild_a else a, guild_b.name if guild_b else b)

    @partner_loop.before_loop
    async def before_partner_loop(self):
        await self.bot.wait_until_ready()
        
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
    async def loop_info(self, interaction: discord.Interaction):
        loop = self.partner_loop

        if not loop.is_running():
            await interaction.response.send_message("`ad_loop` is not running.", ephemeral=True)
            return

        next_iter = loop.next_iteration

        embed = discord.Embed(title="Ad Loop Info", color=discord.Color.fuchsia())
        embed.add_field(name="Running", value=str(loop.is_running()), inline=True)
        embed.add_field(name="Failed", value=str(loop.failed()), inline=True)
        embed.add_field(name="Next Run", value=f"<t:{int(next_iter.timestamp())}:R>", inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)
    
    @partnerGroup.command(name="loopforce")
    @is_owner()
    async def forceloop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        logging.debug("Forcing partner loop")
        await self.redis.delete("last_partner_run")
        await self.partner_loop()
        await interaction.followup.send("Partner loop complete", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))