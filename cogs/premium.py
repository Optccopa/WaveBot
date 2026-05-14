import discord
from discord.ext import commands
from src.checks import is_owner, is_guild_owner

VALID_PINGS = {"none", "partner", "here", "partnerhere", "member"}
ALL_PINGS = ["none", "partner", "here", "partnerhere", "member"]

class Premium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    premiumGroup = discord.app_commands.Group(
        name="premium",
        description="Premium management"
    )

    @premiumGroup.command(name="add", description="Grant premium to a server")
    @is_owner()
    async def premium_add(self, interaction: discord.Interaction, guild_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.followup.send("Invalid guild id.", ephemeral=True)
            return
        existing = await self.bot.premium.get(gid)
        if existing:
            await interaction.followup.send("That server already has premium.", ephemeral=True)
            return
        await self.bot.premium.add(gid, interaction.user.id)
        guild = self.bot.get_guild(gid)
        name = guild.name if guild else str(gid)
        await interaction.followup.send(f"Added **{name}** to premium.", ephemeral=True)

    @premiumGroup.command(name="remove", description="Remove premium from a server")
    @is_owner()
    async def premium_remove(self, interaction: discord.Interaction, guild_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.followup.send("Invalid guild id.", ephemeral=True)
            return
        existing = await self.bot.premium.get(gid)
        if not existing:
            await interaction.followup.send("That server does not have premium.", ephemeral=True)
            return
        await self.bot.premium.remove(gid)
        guild = self.bot.get_guild(gid)
        name = guild.name if guild else str(gid)
        await interaction.followup.send(f"Removed **{name}** from premium.", ephemeral=True)

    @premiumGroup.command(
        name="configset",
        description="Set premium config for this server"
    )
    @is_guild_owner()
    @discord.app_commands.describe(
        available_pings='Comma-separated ping types, or "all". Valid: none, partner, here, partnerhere, member'
    )
    async def premium_configset(
        self,
        interaction: discord.Interaction,
        available_pings: str | None = None
    ):
        await interaction.response.defer(ephemeral=True)
        data = await self.bot.premium.get(interaction.guild.id)
        if not data:
            await interaction.followup.send("This server does not have premium.", ephemeral=True)
            return

        fields = {}
        if available_pings is not None:
            if available_pings.strip().lower() == "all":
                fields["available_pings"] = ALL_PINGS
            else:
                tokens = [t.strip().lower() for t in available_pings.split(",") if t.strip()]
                invalid = [t for t in tokens if t not in VALID_PINGS]
                if invalid:
                    await interaction.followup.send(
                        f"Invalid ping type(s): {', '.join(invalid)}. Valid: {', '.join(ALL_PINGS)}, or `all`.",
                        ephemeral=True
                    )
                    return
                fields["available_pings"] = tokens

        if not fields:
            await interaction.followup.send("No changes provided.", ephemeral=True)
            return

        await self.bot.premium.set(interaction.guild.id, **fields)
        await interaction.followup.send("Premium config updated.", ephemeral=True)

    @premiumGroup.command(name="configview", description="View premium config for this server")
    @is_guild_owner()
    async def premium_configview(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = await self.bot.premium.get(interaction.guild.id)
        if not data:
            await interaction.followup.send("This server does not have premium.", ephemeral=True)
            return

        embed = discord.Embed(title="Premium Config", color=discord.Color.gold())
        embed.add_field(name="Guild", value=interaction.guild.name, inline=False)
        embed.add_field(name="Added by", value=f"<@{data['added_by']}>", inline=True)
        embed.add_field(name="Added at", value=data.get("added_at", "Unknown"), inline=True)
        pings = data.get("available_pings") or []
        embed.add_field(name="Available Pings", value=", ".join(pings) if pings else "None set", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Premium(bot))
