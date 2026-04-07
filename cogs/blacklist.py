from discord.ext import tasks, commands
import re

LINK_REGEX = re.compile(r"https?://\S+")

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = bot.redis
async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))