from discord.ext import tasks, commands
from redis.asyncio import Redis
import re, discord

LINK_REGEX = re.compile(r"https?://\S+")

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.AutoShardedBot = bot
        self.redis: Redis = bot.redis

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ad_loop.is_running():
            self.ad_loop.start()

    @tasks.loop(seconds=900)  # 15 minutes
    async def ad_loop(self):
        await self.index_ads()

    async def index_ads(self):
        missingChannelEmbed = discord.Embed(
            title="Ad channel missing",
            description="Use `/config set` to set one",
            color=discord.Color.dark_red()
        )
        missingAdEmbed = discord.Embed(
            title="Ad message missing",
            description="Your ad message was not found in the recent 10 messages in the channel",
            color=discord.Color.dark_red()
        )
        async with self.redis.pipeline() as pipeline:
            for guild in self.bot.guilds:
                guild: discord.Guild
                config = await self.bot.config.get(guild.id)
                if not config:
                    continue

                ad_channel = guild.get_channel(config.get("ad_channel"))
                log_channel = guild.get_channel(config.get("log_channel"))

                if not ad_channel:
                    if log_channel:
                        await log_channel.send(embed=missingChannelEmbed)
                    continue

                ad_message = None
                async for message in ad_channel.history(limit=10):
                    if LINK_REGEX.search(message.content):
                        ad_message = message.content
                        break

                if ad_message:
                    await pipeline.set(f"ads:{guild.id}", ad_message)
                else:
                    if log_channel:
                        await log_channel.send(embed=missingAdEmbed)

            await pipeline.execute() 

    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()
        
    async def cog_load(self):
        if self.bot.is_ready() and not self.ad_loop.is_running():
            self.ad_loop.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))