from discord.ext import tasks, commands
import discord

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ad_loop.is_running():
            self.ad_loop.start()

    @tasks.loop(seconds=1800) # 30 minutes
    async def ad_loop(self):
        # loops here
        for guild in self.bot.guilds:
            print(guild.name, guild.id)
        pass
            

    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))