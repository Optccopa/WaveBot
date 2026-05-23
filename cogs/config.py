import discord
from discord import app_commands
from discord.ext import commands
from main import Bot
from src.checks import is_management

class Setup(commands.Cog):
    def __init__(self, bot):
        self.bot: Bot = bot

    config = app_commands.Group(
        name="config",
        description="Config management"
    )

    @config.command(name="set", description="Configure this bot")
    @app_commands.checks.cooldown(1, 10)
    @is_management()
    @app_commands.describe(
        partner_channel="Channel to send partners",
        ad_channel="The channel with your ad, uses a recent message with a link.",
        log_channel="Channel for WaveBot to send messages / warnings, set this to a private channel",
        member_role=r"A role assigned to > 95% of users in your server",
        partner_ping_role=r"A role pinged only for partners, must be assigned to > 8% of users in your server",
        partner_delay_hours="How often this server receives a partner (hours)"
    )
    async def setconfig(
        self,
        interaction: discord.Interaction,
        partner_channel: discord.TextChannel | None = None,
        ad_channel: discord.TextChannel | None = None,
        log_channel: discord.TextChannel | None = None,
        member_role: discord.Role | None = None,
        partner_ping_role: discord.Role | None = None,
        partner_delay_hours: int | None = None
    ):
        pd_cfg = self.bot.yaml_config['partner_delay']
        min_h = pd_cfg['min'] // 3600
        max_h = pd_cfg['max'] // 3600

        if partner_delay_hours is not None and not (min_h <= partner_delay_hours <= max_h):
            return await interaction.response.send_message(
                f"Partner delay must be between {min_h} and {max_h} hours.",
                ephemeral=True
            )

        if not any([partner_channel, ad_channel, member_role, partner_ping_role, log_channel, partner_delay_hours]):
            return await interaction.response.send_message(
                "Set at least one config element to set",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        warnings = []
        reqs = self.bot.yaml_config['requirements']

        # partner channel permission check
        if partner_channel:
            perms = partner_channel.permissions_for(interaction.guild.me)
            missing = []
            if not perms.send_messages:
                missing.append("Send Messages")
            if not perms.mention_everyone:
                missing.append("Mention Everyone")
            if missing:
                return await interaction.followup.send(
                    f"I'm missing the following permissions in {partner_channel.mention}:\n{"\n".join(f"- **{p}**" for p in missing)}",
                    ephemeral=True
                )

        # soft coverage warnings
        if member_role:
            total = interaction.guild.member_count or 1
            coverage = len(member_role.members) / total
            min_member = reqs['member_role_min_coverage']
            if coverage < min_member:
                warnings.append(
                    f"**{member_role.name}** only covers {coverage:.0%} of your server, the requirement is {round(min_member * 100)}%."
                )

        if partner_ping_role:
            total = interaction.guild.member_count or 1
            coverage = len(partner_ping_role.members) / total
            min_partner = reqs['partner_role_min_coverage']
            if coverage < min_partner:
                warnings.append(
                    f"**{partner_ping_role.name}** only covers {coverage:.0%} of your server, the requirement is {round(min_partner * 100)}%."
                )

        fields = {}

        if partner_channel: fields["partner_channel"] = partner_channel.id
        if ad_channel: fields["ad_channel"] = ad_channel.id
        if log_channel: fields["log_channel"] = log_channel.id
        if member_role: fields["member_role"] = member_role.id
        if partner_ping_role: fields["partner_ping_role"] = partner_ping_role.id
        if partner_delay_hours is not None: fields["partner_delay"] = partner_delay_hours * 3600

        current = await self.bot.config.get(interaction.guild.id) or {}
        merged = {**current, **fields}
        if all(merged.get(f) for f in ("member_role", "partner_ping_role", "partner_channel")):
            partner_cog = self.bot.cogs.get('Partner')
            if partner_cog:
                reason = await partner_cog.validate_server(interaction.guild, merged)
                if reason:
                    return await interaction.response.send_message(
                        f"Configuration not saved, {reason}",
                        ephemeral=True
                    )

        await self.bot.config.set(
            interaction.guild.id,
            **fields
        )

        ad_cached = None
        if "ad_channel" in fields:
            partner_cog = self.bot.cogs.get('Partner')
            if partner_cog:
                ad_cached = await partner_cog.index_ad(interaction.guild.id)

        config = await self.bot.config.get(interaction.guild.id)
        log_ch = interaction.guild.get_channel(config.get('log_channel'))
        log_mention = log_ch.mention if log_ch else "your log channel (not set)"

        if ad_cached is False:
            warnings.append("No ad found in your ad channel.")

        lines = ["Configuration saved"]
        if warnings:
            lines.append("\nIssues found:")
            lines.extend(f"- {w}" for w in warnings)
        else:
            lines.append(f"\nReady!, watch {log_mention} for any warnings or issues")

        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @config.command(name="view", description="View server configuration")
    @app_commands.checks.cooldown(rate=1, per=10)
    @is_management()
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
        log_channel = guild.get_channel(config.get("log_channel"))
        member_role = guild.get_role(config.get("member_role"))
        partner_ping_role = guild.get_role(config.get("partner_ping_role"))
        premium = config.get("premium", False)
        partner_delay_h = (config.get("partner_delay") or self.bot.yaml_config['partner_delay']['default']) // 3600

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
            name="Log Channel",
            value=log_channel.mention if log_channel else "Not set",
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
            name="Partner Cooldown",
            value=f"{partner_delay_h}h",
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