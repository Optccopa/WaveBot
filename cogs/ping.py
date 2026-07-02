import discord, time
from main import Bot
from discord.ext import commands


class Ping(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: Bot = bot

    @commands.command()
    @commands.cooldown(1, 10)
    async def ping(self, ctx):
        start = time.perf_counter()

        embed = discord.Embed(description="Pinging...", color=discord.Color.fuchsia())

        msg = await ctx.send(embed=embed)

        api_latency = round(self.bot.latency * 1000)

        db_latency = "N/A"
        if hasattr(self.bot, "db_pool"):
            try:
                db_start = time.perf_counter()
                async with self.bot.db_pool.acquire() as conn:
                    await conn.execute("SELECT 1")
                db_latency = f"{round((time.perf_counter() - db_start) * 1000)}ms"
            except Exception:
                db_latency = "Error"

        redis_latency = "N/A"
        if hasattr(self.bot, "redis"):
            try:
                redis_start = time.perf_counter()
                await self.bot.redis.ping()
                redis_latency = f"{round((time.perf_counter() - redis_start) * 1000)}ms"
            except Exception:
                redis_latency = "Error"

        edit_latency = round((time.perf_counter() - start) * 1000)

        embed = discord.Embed(
            description=(
                f"Api: `{api_latency}ms`\n"
                f"Edit: `{edit_latency}ms`\n"
                f"Database: `{db_latency}`\n"
                f"Cache: `{redis_latency}`"
            ),
            color=discord.Color.fuchsia(),
        )

        await msg.edit(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))
