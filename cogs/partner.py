from discord.ext import tasks, commands
from src.checks import is_owner
from redis.asyncio import Redis
from asyncpg import Pool
import discord, random

class AddBotView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Add WaveBot", style=discord.ButtonStyle.blurple, custom_id="wavebot:add_bot")
    async def add_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Add WaveBot to your server!",
            color=discord.Color.blurple()
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
                  "- Your **logging channel** (for errors and warnings)",
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
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def check_partner_requirements(guild, channel, config):
    member_role  = guild.get_role(config.get("member_role"))
    partner_role = guild.get_role(config.get("partner_ping_role"))

    if not member_role:
        return False, "Member role not configured"
    if not partner_role:
        return False, "Partner role not configured"
    
    if sum(1 for m in guild.member_count if channel.permissions_for(m).view_channel) / guild.member_count < 0.95:
        return False, r"Less than 95% of server members can see the partner channel, Make sure your partner channel is visible to everyone"
    
    if sum(1 for m in member_role.members if channel.permissions_for(m).view_channel) / guild.member_count < 0.95:
        return False, r"Less than 95% of members can see the partner channel, Try giving more people member role or make sure your partner channel is visible"
    
    if partner_role and len(partner_role.members) / guild.member_count < 0.08:
        return False, r"Less than 8% of members have partner ping role"
    
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
            break

    return {"server_a": ping_a, "server_b": ping_b, "host": "server_a" if a_is_host else "server_b"}

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
        result = bool(await self.redis.exists(f"partner_cooldown:{min(a,b)}:{max(a,b)}"))
        return result

    async def set_cooldown(self, a: int, b: int):
        await self.redis.set(f"partner_cooldown:{min(a,b)}:{max(a,b)}", 1, ex=60 * 60 * 24 * 7)

    async def match_servers(self, guilds: list[tuple[int, int]]) -> list[tuple[int, int]]:
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
                    matched = True
                    break
            if not matched:
                print(f"[match] no valid partner found for {server} (all on cooldown or exhausted)")
        print(f"[match] result: {len(pairs)} pairs")
        return pairs

    async def partner(self, server1_id: int, server2_id: int):

        config1 = await self.bot.config.get(server1_id)
        config2 = await self.bot.config.get(server2_id)
        if not config1 or not config2:
            return None, None

        guild1 = self.bot.get_guild(server1_id)
        guild2 = self.bot.get_guild(server2_id)
        if not guild1 or not guild2:
            return None, None

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        if not channel1 or not isinstance(channel1, discord.TextChannel):
            log_channel = guild1.get_channel(config1.get("log_channel"))
            if log_channel:
                embed = discord.Embed(
                    title="Partner channel not found",
                    description="Use `/config set` to set one",
                    color=discord.Color.dark_red()
                )
                await log_channel.send(embed=embed)
            return None, None
        
        channel2 = guild2.get_channel(config2.get("partner_channel"))
        if not channel2 or not isinstance(channel2, discord.TextChannel):
            log_channel = guild2.get_channel(config2.get("log_channel"))
            if log_channel:
                embed = discord.Embed(
                    title="Partner channel not found",
                    description="Use `/config set` to set one",
                    color=discord.Color.dark_red()
                )
                await log_channel.send(embed=embed)
            return None, None
        
        for guild, channel, config in [(guild1, channel1, config1), (guild2, channel2, config2)]:
            passed, reason = await check_partner_requirements(guild, channel, config)
            if not passed:
                log = guild.get_channel(config.get("log_channel"))
                if log: await log.send(embed=discord.Embed(title="Requirements not met", description=reason, color=discord.Color.dark_red()))
                print("Partner refused, reason:", reason)
                return None, None

        r = get_req(guild1.member_count, guild2.member_count)
        print(f"[partner] {server1_id}({guild1.member_count}) pings {r['server_a']} | {server2_id}({guild2.member_count}) pings {r['server_b']} | host: {r['host']}")

        raw_ad1 = await self.redis.get(f'ads:{server1_id}')
        raw_ad2 = await self.redis.get(f'ads:{server2_id}')

        if not raw_ad1 or not raw_ad2:
            return None, None
        
        perms1 = channel1.permissions_for(channel1.guild.me)
        if not perms1.send_messages or not perms1.mention_everyone:
            log_channel = guild1.get_channel(config1.get("log_channel"))
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    title="Missing permissions",
                    description="I need `Send Messages` and `Mention Everyone` permissions in the partner channel",
                    color=discord.Color.dark_red()
                ))
            return None, None

        perms2 = channel2.permissions_for(channel2.guild.me)
        if not perms2.send_messages or not perms2.mention_everyone:
            log_channel = guild2.get_channel(config2.get("log_channel"))
            if log_channel:
                await log_channel.send(embed=discord.Embed(
                    title="Missing permissions",
                    description="I need `Send Messages` and `Mention Everyone` in the partner channel",
                    color=discord.Color.dark_red()
                ))
            return None, None
        
        ad1 = f"{raw_ad1}\n\n{r['server_a']} (Testing Placeholder)"
        ad2 = f"{raw_ad2}\n\n{r['server_b']} (Testing Placeholder)"

        if len(ad1) > 2000 or len(ad2) > 2000:
            return None, None
        
        try:
            await channel1.send(ad2, view=AddBotView())
        except Exception as e:
            print(e)
            return None, None
        try:
            await channel2.send(ad1, view=AddBotView())
        except Exception as e:
            print(e)
            return None, None
            
        await self.set_cooldown(server1_id, server2_id)
        return channel1, channel2

    async def cog_load(self):
        self.bot.add_view(AddBotView())
        if self.bot.is_ready() and not self.partner_loop.is_running():
            self.partner_loop.start()

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(AddBotView())
        if not self.partner_loop.is_running():
            self.partner_loop.start()

    @tasks.loop(seconds=21600)
    async def partner_loop(self):
        if await self.redis.exists("last_partner_run"):
            return
        await self.redis.set("last_partner_run", 1, ex=10800)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id FROM blacklists")
            blacklisted_ids = {row[0] for row in rows}

        available = []
        for guild in self.bot.guilds:
            if guild.id in blacklisted_ids:
                continue
            config = await self.bot.config.get(guild.id)
            if not config:
                continue

            partner_channel = guild.get_channel(config.get("partner_channel"))
            ad_channel = guild.get_channel(config.get("ad_channel"))
            member_role = guild.get_role(config.get("member_role"))
            partner_ping_role = guild.get_role(config.get("partner_ping_role"))

            if not all([partner_channel, ad_channel, member_role, partner_ping_role]):
                continue

            ad = await self.redis.get(f"ads:{guild.id}")
            if not ad:
                continue

            available.append((guild.id, guild.member_count))

        pairs = await self.match_servers(available)

        for a, b in pairs:
            await self.partner(a, b)

    @partner_loop.before_loop
    async def before_partner_loop(self):
        await self.bot.wait_until_ready()
        
    @partnerGroup.command(name="force")
    @is_owner()
    async def force_partner(self, interaction: discord.Interaction, server_id_1: str, server_id_2: str):
        if server_id_1 == server_id_2:
            return
        channel1, channel2 = await self.partner(int(server_id_1), int(server_id_2))
        if not channel1:
            await interaction.response.send_message("Failed - check configs and channels.", ephemeral=True)
            return
        await interaction.response.send_message(f"Partnered: {channel1.mention} | {channel2.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))