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
        available_pings='Available pings, or all, example: none, partner, here, partnerhere, member'
    )
    async def premium_configset(
        self,
        interaction: discord.Interaction,
        available_pings: str | None = None
    ):
        data = await self.bot.premium.get(interaction.guild.id)
        if not data:
            return await interaction.response.send_message("This server does not have premium.", ephemeral=True)

        if not any([available_pings]):
            return await interaction.response.send_message("Set at least one config element to set", ephemeral=True)

        fields = {}
        if available_pings is not None:
            if available_pings.strip().lower() == "all":
                fields["available_pings"] = ALL_PINGS
            else:
                tokens = [t.strip().lower() for t in available_pings.split(",") if t.strip()]
                invalid = [t for t in tokens if t not in VALID_PINGS]
                if invalid:
                    return await interaction.response.send_message(
                        f"Invalid ping type(s): {', '.join(invalid)}. Valid: {', '.join(ALL_PINGS)}, or `all`.",
                        ephemeral=True
                    )
                fields["available_pings"] = tokens

        await self.bot.premium.set(interaction.guild.id, **fields)
        await interaction.response.send_message("Premium configuration updated.", ephemeral=True)

    @premiumGroup.command(name="configview", description="View premium config for this server")
    @is_guild_owner()
    async def premium_configview(self, interaction: discord.Interaction):
        data = await self.bot.premium.get(interaction.guild.id)
        if not data:
            return await interaction.response.send_message("This server does not have premium.", ephemeral=True)

        pings = data.get("available_pings") or []

        embed = discord.Embed(
            title="Premium Configuration",
            color=discord.Color.fuchsia()
            )

        embed.add_field(
            name="Available Pings",
            value=", ".join(pings) if pings else "Not set",
            inline=False
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Premium(bot))
