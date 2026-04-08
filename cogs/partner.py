from discord.ext import tasks, commands
from discord import app_commands
import discord, random

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
    for ceiling, host_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, "member"
            else:
                ping_a, ping_b = "member", host_ping
            return {
                "server_a": ping_a,
                "server_b": ping_b,
                "host": "server_a" if a_is_host else "server_b",
            }

class Partner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = bot.redis
        self.db_pool = bot.db_pool

    async def has_cooldown(self, a: int, b: int) -> bool:
        return bool(await self.redis.exists(f"partner_cooldown:{min(a,b)}:{max(a,b)}"))

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
            for candidate in candidates:
                if not await self.has_cooldown(server, candidate):
                    pairs.append((server, candidate))
                    used.update([server, candidate])
                    break
        return pairs

    async def partner(self, server1_id: int, server2_id: int):
        config1 = self.bot.config.get(server1_id)
        config2 = self.bot.config.get(server2_id)
        if not config1 or not config2:
            return None, None

        guild1 = self.bot.get_guild(server1_id)
        guild2 = self.bot.get_guild(server2_id)
        if not guild1 or not guild2:
            return None, None

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        channel2 = guild2.get_channel(config2.get("partner_channel"))
        if not channel1 or not channel2:
            return None, None

        r = get_req(guild1.member_count, guild2.member_count)
        raw_ad1 = await self.redis.get(f'ads:{server1_id}') or ""
        raw_ad2 = await self.redis.get(f'ads:{server2_id}') or ""

        await channel1.send(f"{raw_ad2}\n\n{r['server_a']} (Testing Placeholder)")
        await channel2.send(f"{raw_ad1}\n\n{r['server_b']} (Testing Placeholder)")

        await self.set_cooldown(server1_id, server2_id)
        return channel1, channel2

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.partner_loop.is_running():
            self.partner_loop.start()

    @tasks.loop(seconds=21600)
    async def partner_loop(self):
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id FROM blacklists")
            blacklisted_ids = {row[0] for row in rows}

        available = []
        for guild in self.bot.guilds:
            if guild.id in blacklisted_ids:
                continue
            config = self.bot.config.get(guild.id)
            if not config:
                continue
            partner_channel = guild.get_channel(config.get("partner_channel"))
            ad_channel = guild.get_channel(config.get("ad_channel"))
            member_role = guild.get_role(config.get("member_role"))
            partner_ping_role = guild.get_role(config.get("partner_ping_role"))
            if all([partner_channel, ad_channel, member_role, partner_ping_role]):
                available.append((guild.id, guild.member_count))

        pairs = await self.match_servers(available)
        for a, b in pairs:
            await self.partner(a, b)
            await self.set_cooldown(a, b)

    @partner_loop.before_loop
    async def before_partner_loop(self):
        await self.bot.wait_until_ready()

    partnerGroup = app_commands.Group(name="partner", description="Partner commands")

    @partnerGroup.command(name="force")
    async def force_partner(self, interaction: discord.Interaction, server_id_1: str, server_id_2: str):
        channel1, channel2 = await self.partner(int(server_id_1), int(server_id_2))
        if not channel1:
            await interaction.response.send_message("Failed - check configs and channels.", ephemeral=True)
            return
        await self.set_cooldown(int(server_id_1), int(server_id_2))
        await interaction.response.send_message(f"Partnered: {channel1.mention} | {channel2.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))