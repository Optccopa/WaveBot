from discord.ext import commands
from discord import app_commands
import discord

class Parter(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = bot.redis
    
    partner = app_commands.Group(
        name="Partner command group",
        description="Group of partner commands"
    )
    @partner.command(name="force")
    async def forcepartner(self, server_id_1: int, server_id_2: int):
        pass # Mkae command im not writing more of ts im gonna go write c++

async def setup(bot: commands.Bot):
    await bot.add_cog(Parter(bot))