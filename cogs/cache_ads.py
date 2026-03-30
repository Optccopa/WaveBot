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

    @tasks.loop(seconds=1800)  # 30 minutes
    async def ad_loop(self):
        await self.index_ads()

    async def index_ads(self):
        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            if not config:
                continue

            ad_channel = guild.get_channel(config.get("partner_channel"))
            if not ad_channel:
                print(f"Ad channel not found for {guild.name}")
                continue

            ad_message = None

            async for message in ad_channel.history(limit=10):
                if LINK_REGEX.search(message.content):
                    ad_message = message.content
                    break

            if ad_message:
                await self.redis.set(f"ads:{guild.id}", ad_message)
                print(f"Cached ad for {guild.name}")
            else:
                print(f"No ad found for {guild.name}")

    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))