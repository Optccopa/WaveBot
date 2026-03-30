import discord
from discord import app_commands
from discord.ext import commands

class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    config = app_commands.Group(
        name="config",
        description="Config management"
    )

    @config.command(name="set", description="Configure this bot")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setconfig(
        self,
        interaction: discord.Interaction,
        partner_channel: discord.TextChannel | None = None,
        ad_channel: discord.TextChannel | None = None,
        member_role: discord.Role | None = None,
        partner_ping_role: discord.Role | None = None
    ):

        if not any([partner_channel, ad_channel, member_role, partner_ping_role]):
            return await interaction.response.send_message(
                "Set at least one config element to set",
                ephemeral=True
            )

        fields = {}

        if partner_channel:
            fields["partner_channel"] = partner_channel.id

        if ad_channel:
            fields["ad_channel"] = ad_channel.id

        if member_role:
            fields["member_role"] = member_role.id

        if partner_ping_role:
            fields["partner_ping_role"] = partner_ping_role.id

        await self.bot.config.set(
            interaction.guild.id,
            **fields
        )

        await interaction.response.send_message(
            "Configuration updated",
            ephemeral=True
        )

    @config.command(name="view", description="View server configuration")
    @app_commands.check()
    async def viewconfig(self, interaction: discord.Interaction):
        config = await self.bot.config.get(interaction.guild.id)

        if not config:
            return await interaction.response.send_message(
                "Server not registered. Use /register first.",
                ephemeral=True
            )

        guild = interaction.guild

        partner_channel = guild.get_channel(config.get("partner_channel"))
        ad_channel = guild.get_channel(config.get("ad_channel"))
        member_role = guild.get_role(config.get("member_role"))
        partner_ping_role = guild.get_role(config.get("partner_ping_role"))
        premium = config.get("premium", False)

        embed = discord.Embed(
            title="Server Configuration",
            color=discord.Color.fuchsia()
        )

        embed.add_field(
            name="Partner Channel",
            value=partner_channel.mention if partner_channel else "Not set",
            inline=False
        )
        embed.add_field(
            name="Ad Channel",
            value=ad_channel.mention if ad_channel else "Not set",
            inline=False
        )
        embed.add_field(
            name="Member Role",
            value=member_role.mention if member_role else "Not set",
            inline=False
        )
        embed.add_field(
            name="Partner Ping Role",
            value=partner_ping_role.mention if partner_ping_role else "Not set",
            inline=False
        )
        embed.add_field(
            name="Premium",
            value="Yes" if premium else "No",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

async def setup(bot):
    await bot.add_cog(Setup(bot))