from discord import app_commands
from discord.ext import commands
from src.checks import is_owner
from src.groups import partnerGroup, blacklistGroup, serversGroup
import discord, asyncpg

class OwnerOnly(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool = bot.db_pool
        self.redis = bot.redis

    @blacklistGroup.command(name="add", description="Blacklist a server")
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

    @blacklistGroup.command(name="remove", description="Remove a blacklist")
    @is_owner()
    async def removeBlacklist(self, interaction: discord.Interaction, guild_id: str):
        async with self.db_pool.acquire() as conn:
            conn: asyncpg.Connection
            await conn.execute("DELETE FROM blacklists WHERE guild_id = $1", int(guild_id))
        await interaction.response.send_message("Server removed from blacklist", ephemeral=True)

    @blacklistGroup.command(name="check", description="Check if a server is blacklisted")
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

    @serversGroup.command(name="list")
    @is_owner()
    async def list_servers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        fields = []
        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            ad = await self.redis.get(f"ads:{guild.id}")
            partner_channel = guild.get_channel(config.get("partner_channel")) if config else None
            ad_channel = guild.get_channel(config.get("ad_channel")) if config else None
            member_role = guild.get_role(config.get("member_role")) if config else None
            partner_ping_role = guild.get_role(config.get("partner_ping_role")) if config else None

            value = (
                f"Members: `{guild.member_count}`\n"
                f"Status: {':green_circle:' if all([config, ad, partner_channel, ad_channel, member_role, partner_ping_role]) else ':red_circle:'}"
            )
            fields.append((guild.name, value))

        for i in range(0, max(len(fields), 1), 25):
            chunk = fields[i:i+25]
            embed = discord.Embed(
                title=f"Servers ({i+1}-{i+len(chunk)} of {len(fields)})",
                color=discord.Color.fuchsia()
            )
            for name, value in chunk:
                embed.add_field(name=name, value=value, inline=False)
            if not fields:
                embed.description = "No servers."
            await interaction.followup.send(embed=embed, ephemeral=True)

    @partnerGroup.command(name="force")
    @is_owner()
    async def force_partner(self, interaction: discord.Interaction, server_id_1: str, server_id_2: str):
        if server_id_1 == server_id_2:
            return
        channel1, channel2 = await self.partner(int(server_id_1), int(server_id_2))
        if not channel1:
            await interaction.response.send_message("Failed - check configs and channels.", ephemeral=True)
            return
        await interaction.response.send_message(f"Partnered: {channel1.mention} | {channel2.mention}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(OwnerOnly(bot))