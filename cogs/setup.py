import discord
from discord import app_commands
from discord.ext import commands

TIMEOUT = 300


class SetupState:
    __slots__ = ("log_channel", "partner_channel", "ad_channel", "member_role", "partner_ping_role")

    def __init__(self):
        self.log_channel: int | None = None
        self.partner_channel: int | None = None
        self.ad_channel: int | None = None
        self.member_role: int | None = None
        self.partner_ping_role: int | None = None


def step_embed(title: str, description: str, color=discord.Color.blurple()) -> discord.Embed:
    embed = discord.Embed(title=title, description=description, color=color)
    embed.set_footer(text="Times out after 5 minutes of inactivity")
    return embed


class WelcomeView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.button(label="Begin Setup", style=discord.ButtonStyle.green)
    async def begin(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = step_embed(
            "Step 1/5 - Log Channel",
            "Select a **private staff-only channel**.\n\n"
            "WaveBot will send warnings, errors, and status messages here. Keep it hidden from regular members."
        )
        await interaction.response.edit_message(embed=embed, view=LogChannelView(self.state, self.bot, self.guild))


class LogChannelView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select your private log channel...",
        channel_types=[discord.ChannelType.text]
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.state.log_channel = select.values[0].id
        embed = step_embed(
            "Step 2/5 - Partner Channel",
            "Select the channel where **partner ads will be posted**.\n\n"
            "**Required bot permissions in this channel:**\n"
            "- Send Messages\n"
            "- Mention Everyone"
        )
        await interaction.response.edit_message(embed=embed, view=PartnerChannelView(self.state, self.bot, self.guild))


class PartnerChannelView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select your partner channel...",
        channel_types=[discord.ChannelType.text]
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        channel = select.values[0]
        resolved = interaction.guild.get_channel(channel.id)

        if resolved:
            perms = resolved.permissions_for(interaction.guild.me)
            missing = []
            if not perms.send_messages:
                missing.append("Send Messages")
            if not perms.mention_everyone:
                missing.append("Mention Everyone")

            if missing:
                embed = step_embed(
                    "Missing Permissions",
                    f"I'm missing the following permissions in {channel.mention}:\n" +
                    "\n".join(f"- {p}" for p in missing) +
                    "\n\nGrant the permissions and select the channel again.",
                    discord.Color.orange()
                )
                await interaction.response.edit_message(embed=embed, view=PartnerChannelView(self.state, self.bot, self.guild))
                return

        self.state.partner_channel = channel.id
        embed = step_embed(
            "Step 3/5 - Ad Channel",
            "Select the channel that contains **your server's advertisement**.\n\n"
            "Your **10 recent messages** in this channel must be contain ad and your `discord.gg` invite link."
        )
        await interaction.response.edit_message(embed=embed, view=AdChannelView(self.state, self.bot, self.guild))


class AdChannelView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.select(
        cls=discord.ui.ChannelSelect,
        placeholder="Select your ad channel...",
        channel_types=[discord.ChannelType.text]
    )
    async def select(self, interaction: discord.Interaction, select: discord.ui.ChannelSelect):
        self.state.ad_channel = select.values[0].id
        embed = step_embed(
            "Step 4/5 - Member Role",
            "Select a role assigned to **95%+ of your server members**.\n\n"
            "This verifies your partner channel is visible to most of your community. "
            "If no such role exists, create one and assign it before continuing."
        )
        await interaction.response.edit_message(embed=embed, view=MemberRoleView(self.state, self.bot, self.guild))


class MemberRoleView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select your member role...")
    async def select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        self.state.member_role = role.id

        member_count = interaction.guild.member_count or 1
        coverage = len(role.members) / member_count

        embed = step_embed(
            "Step 5/5 - Partner Ping Role",
            "Select the role that gets **pinged when a partner ad is posted**.\n\n"
            "**Requirements:**\n"
            "- At least **8%** of your server must have this role\n"
            "- This should be opt-in so members can self-assign it"
        )

        if coverage < 0.95:
            embed.description += (
                f"\n\n> **{role.name}** only covers {coverage:.0%} of your server. "
                "The requirement is 95% - you may be skipped in partner rounds until this is resolved."
            )

        await interaction.response.edit_message(embed=embed, view=PartnerPingRoleView(self.state, self.bot, self.guild))


class PartnerPingRoleView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.select(cls=discord.ui.RoleSelect, placeholder="Select your partner ping role...")
    async def select(self, interaction: discord.Interaction, select: discord.ui.RoleSelect):
        role = select.values[0]
        self.state.partner_ping_role = role.id

        guild = interaction.guild
        member_count = guild.member_count or 1
        coverage = len(role.members) / member_count

        log_ch = guild.get_channel(self.state.log_channel)
        partner_ch = guild.get_channel(self.state.partner_channel)
        ad_ch = guild.get_channel(self.state.ad_channel)
        member_r = guild.get_role(self.state.member_role)
        partner_r = guild.get_role(self.state.partner_ping_role)

        embed = discord.Embed(
            title="Review & Confirm",
            description="Here's your configuration. Click **Confirm** to save or **Cancel** to abort.",
            color=discord.Color.green()
        )
        embed.add_field(name="Log Channel", value=log_ch.mention if log_ch else "Unknown", inline=False)
        embed.add_field(name="Partner Channel", value=partner_ch.mention if partner_ch else "Unknown", inline=False)
        embed.add_field(name="Ad Channel", value=ad_ch.mention if ad_ch else "Unknown", inline=False)
        embed.add_field(name="Member Role", value=member_r.mention if member_r else "Unknown", inline=False)
        embed.add_field(name="Partner Ping Role", value=partner_r.mention if partner_r else "Unknown", inline=False)

        if coverage < 0.08:
            embed.add_field(
                name="Warning",
                value=f"**{role.name}** only covers {coverage:.0%} of your server. "
                      "The requirement is 8% - you'll be skipped in partner rounds until this is fixed.",
                inline=False
            )

        await interaction.response.edit_message(embed=embed, view=ConfirmView(self.state, self.bot, guild))


class ConfirmView(discord.ui.View):
    def __init__(self, state: SetupState, bot, guild: discord.Guild):
        super().__init__(timeout=TIMEOUT)
        self.state = state
        self.bot = bot
        self.guild = guild

    @discord.ui.button(label="Confirm & Save", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.bot.config.set(
            self.guild.id,
            log_channel=self.state.log_channel,
            partner_channel=self.state.partner_channel,
            ad_channel=self.state.ad_channel,
            member_role=self.state.member_role,
            partner_ping_role=self.state.partner_ping_role,
        )
        embed = discord.Embed(
            title="Setup Complete",
            description=(
                "Configuration saved.\n\n"
                "**Next steps:**\n"
                "1. Post your server ad in your ad channel - it must include your `discord.gg` invite link\n"
                "2. WaveBot will automatically run partner rounds every 6 hours\n"
                "3. Watch your log channel for any warnings\n\n"
                "Use `/config view` to review your settings at any time."
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="Setup Cancelled",
            description="No changes were saved. Run `/setup` again to start over.",
            color=discord.Color.dark_gray()
        )
        await interaction.response.edit_message(embed=embed, view=None)


class SetupCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Interactive guide to set up WaveBot for your server")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        state = SetupState()
        embed = step_embed(
            "WaveBot Setup Wizard",
            "This wizard will walk you through configuring WaveBot.\n\n"
            "**You will set up:**\n"
            "- A private log channel for bot messages\n"
            "- Your partner channel (where ads get posted)\n"
            "- Your ad channel (where your server ad lives)\n"
            "- A member role (assigned to 95%+ of members)\n"
            "- A partner ping role (assigned to 8%+ of members)\n\n"
            "Click **Begin Setup** to start."
        )
        await interaction.response.send_message(
            embed=embed,
            view=WelcomeView(state, self.bot, interaction.guild),
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(SetupCog(bot))
