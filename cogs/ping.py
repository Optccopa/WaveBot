import time
import discord
from discord import app_commands
from discord.ext import commands

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="ping", description="Check bot latency and service health")
    @app_commands.Cooldown(1, 10)
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.defer()

        ws_latency = round(self.bot.latency * 1000)

        try:
            t = time.monotonic()
            await self.bot.redis.ping()
            redis_latency = round((time.monotonic() - t) * 1000)
            redis_status = f":green_circle: {redis_latency}ms"
        except Exception:
            redis_status = ":red_circle: Unreachable"

        try:
            t = time.monotonic()
            async with self.bot.db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            db_latency = round((time.monotonic() - t) * 1000)
            db_status = f":green_circle: {db_latency}ms"
        except Exception:
            db_status = ":red_circle: Unreachable"

        t = time.monotonic()
        msg = await interaction.followup.send("...")
        rtt = round((time.monotonic() - t) * 1000)
        await msg.delete()

        # WS status indicator
        if ws_latency < 100:
            ws_status = f":green_circle: {ws_latency}ms"
        elif ws_latency < 200:
            ws_status = f":orange_circle: {ws_latency}ms"
        else:
            ws_status = f":red_circle: {ws_latency}ms"

        embed = discord.Embed(
            title=":ping_pong: Pong",
            color=discord.Color.fuchsia()
        )
        embed.add_field(name="Websocket", value=ws_status, inline=True)
        embed.add_field(name="Round trip", value=f":green_circle: {rtt}ms", inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer
        embed.add_field(name="Redis", value=redis_status, inline=True)
        embed.add_field(name="Database", value=db_status, inline=True)
        embed.add_field(name="\u200b", value="\u200b", inline=True)  # spacer

        await interaction.followup.send(embed=embed)

async def setup(bot):
    await bot.add_cog(Ping(bot))