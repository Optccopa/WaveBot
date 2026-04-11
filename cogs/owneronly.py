from discord import app_commands
from discord.ext import commands
from src.checks import is_owner
import discord, asyncpg

class Blacklists(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = bot.db_pool

    blacklist = app_commands.Group(name="blacklist", description="Server blacklist management")

    @blacklist.command(name="add", description="Blacklist a server")
    @is_owner()
    async def addBlacklist(self, interaction: discord.Interaction, guild_id: str, reason: str = "No reason provided"):
        async with self.db_pool.acquire() as conn:
            conn: asyncpg.Connection
            await conn.execute(
                "INSERT INTO blacklists (guild_id, reason, added_by) VALUES ($1, $2, $3)"
                " ON CONFLICT (guild_id) DO UPDATE SET reason = $2, added_by = $3",
                int(guild_id), reason, interaction.user.id
            )
        embed = discord.Embed(
            title="Added Blacklist",
            description=f"Reason: {reason}"
        )
        await interaction.response.send_message(embed=embed)

    @blacklist.command(name="remove", description="Remove a blacklist")
    @is_owner()
    async def removeBlacklist(self, interaction: discord.Interaction, guild_id: str):
        async with self.db_pool.acquire() as conn:
            conn: asyncpg.Connection
            await conn.execute("DELETE FROM blacklists WHERE guild_id = $1", int(guild_id))
        await interaction.response.send_message("Server removed from blacklist", ephemeral=True)

    @blacklist.command(name="check", description="Check if a server is blacklisted")
    @is_owner()
    async def checkBlacklist(self, interaction: discord.Interaction, guild_id: str):
        async with self.db_pool.acquire() as conn:
            conn: asyncpg.Connection
            row = await conn.fetchrow("SELECT * FROM blacklists WHERE guild_id = $1", int(guild_id))
        if row:
            embed = discord.Embed(
                title="Blacklisted",
                description=f"Reason: {row['reason']}"
            )
            await interaction.response.send_message(embed=embed)
        else:
            await interaction.response.send_message("Not blacklisted", ephemeral=True)
        


async def setup(bot: commands.Bot):
    await bot.add_cog(Blacklists(bot))