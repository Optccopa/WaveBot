import time
import discord
from discord import app_commands
from discord.ext import commands
from redis.asyncio import Redis
from asyncpg import Pool

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.redis: Redis = bot.redis
        self.db_pool: Pool = bot.db_pool

    @app_commands.command(name="ping", description="Check bot latency and service health")
    async def ping(self, interaction: discord.Interaction):
        cooldown_key = f"cooldown:ping:{interaction.user.id}"
        ttl = await self.redis.ttl(cooldown_key)

        if ttl > 0:
            retry_at = int(time.time() + ttl)
            await interaction.response.send_message(
                f"Slow down! Try again <t:{retry_at}:R>",
                ephemeral=True
            )
            return

        await self.redis.set(cooldown_key, 1, ex=10)
        await interaction.response.defer()

        ws_latency = round(self.bot.latency * 1000)

        if ws_latency < 100:
            ws_status = f":green_circle: {ws_latency}ms"
        elif ws_latency < 200:
            ws_status = f":yellow_circle: {ws_latency}ms"
        else:
            ws_status = f":red_circle: {ws_latency}ms"

        try:
            t = time.monotonic()
            await self.redis.ping()
            redis_latency = round((time.monotonic() - t) * 1000)
            redis_status = f":green_circle: {redis_latency}ms"
        except Exception:
            redis_status = ":red_circle: Unreachable"

        try:
            t = time.monotonic()
            async with self.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_latency = round((time.monotonic() - t) * 1000)
            db_status = f":green_circle: {db_latency}ms"
        except Exception:
            db_status = ":red_circle: Unreachable"

        t = time.monotonic()
        msg = await interaction.followup.send("...")
        rtt = round((time.monotonic() - t) * 1000)
        await msg.delete()

        embed = discord.Embed(title=":ping_pong: Pong!", color=discord.Color.fuchsia())
        embed.add_field(name="Websocket",    value=ws_status,            inline=True)
        embed.add_field(name="Round-trip",   value=f":green_circle: {rtt}ms", inline=True)
        embed.add_field(name="\u200b",       value="\u200b",             inline=True)
        embed.add_field(name="Redis",        value=redis_status,         inline=True)
        embed.add_field(name="Database",     value=db_status,            inline=True)
        embed.add_field(name="\u200b",       value="\u200b",             inline=True)

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Ping(bot))