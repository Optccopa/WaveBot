import discord
from discord import app_commands

class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
async def setup(bot):
    await bot.add_cog(BotCommands(bot))