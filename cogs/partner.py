from discord.ext import commands
from discord import app_commands
import discord

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
        (round(400 * scale), "none", "member"),
        (round(800 * scale), "partner", "member"),
        (round(1700 * scale), "here", "member"),
        (round(2000 * scale), "partnerhere", "member"),
        (float("inf"), "member", "member")
    ]

    for ceiling, host_ping, guest_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, guest_ping
            else:
                ping_a, ping_b = guest_ping, host_ping

            return {
                "server_a": ping_a,
                "server_b": ping_b,
                "host": "server_a" if a_is_host else "server_b",
            }

class Parter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = bot.redis
    
    async def partner(self, server1_id: int, server2_id: int, ping: bool = True):

        config1 = await self.bot.config.get(server1_id)
        config2 = await self.bot.config.get(server2_id)

        if not config1 or not config2:
            return "Config missing"
        
        guild1 = self.bot.get_guild(server1_id)
        guild2 = self.bot.get_guild(server2_id)

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        channel2 = guild2.get_channel(config2.get("partner_channel"))

        r = get_req(len(guild1.members), len(guild2.members))

        ad1 = f"{self.redis.get(f"ads:{server1_id}")}\n\n{r['server_a']}"
        ad2 = f"{self.redis.get(f"ads:{server2_id}")}\n\n{r['server_b']}"

        await channel1.send(ad2)
        await channel1.send(ad1)

        return channel1, channel2
    
    partnerGroup = app_commands.Group(
        name="Partner command group",
        description="Group of partner commands"
    )
    
    @partnerGroup.command(name="force")
    async def forcepartner(self, interaction: discord.Interaction, server_id_1: int, server_id_2: int):
        channel1, channel2, _t = await self.partner(server_id_1, server_id_2)
        await interaction.response.send_message(f"Send partner with respective pings, {channel1.mention} | {channel2.mention}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Parter(bot))