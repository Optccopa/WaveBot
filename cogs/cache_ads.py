from discord.ext import tasks, commands
import discord, re

LINK_REGEX = re.compile(r"https?://\S+")

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis = bot.redis

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ad_loop.is_running():
            self.ad_loop.start()
            self.index_ads # does when bot starts so it doesnt wait 30 mins till it has ads

    @tasks.loop(seconds=1800) # 30 minutes
    async def ad_loop(self):
        self.index_ads

    async def index_ads(self):
        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            if not config:
                return
            ad_channel = guild.get_channel(config.get("partner_channel"))

            async for message in ad_channel.history(limit=10):
                if LINK_REGEX.search(message.content):
                    ad_message = message.content
                    break
            if ad_message:
                await self.redis.set(f"ads:{guild.id}", ad_message)
                print(ad_message)
            else:
                print(f"Log channel not found for {guild.name}")
    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))