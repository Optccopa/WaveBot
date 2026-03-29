from discord.ext import commands

class Test(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def redis(self, ctx):
        await self.bot.redis.set("test", "hello")
        value = await self.bot.redis.get("test")
        await ctx.send(f"Redis: {value}")

    @commands.command()
    async def pg(self, ctx):
        async with self.bot.db_pool.acquire() as conn:
            value = await conn.fetchval("SELECT 1")
            await ctx.send(f"Postgres: {value}")

async def setup(bot):
    await bot.add_cog(Test(bot))