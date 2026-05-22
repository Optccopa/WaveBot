import discord, traceback, logging, asyncio
from time import time
from discord.ext import commands
from src.checks import is_owner
from main import Bot

_cooldown_notified: set[int] = set()

log = logging.getLogger(__name__)

class ErrorHandler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot: Bot = bot
        self.last_errors = {
            "slash": None,
            "prefix": None,
            "event": None
        }
        self.bot.tree.on_error = self.on_app_command_error

    # Slash commands
    async def on_app_command_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
        if isinstance(error, discord.app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        elif isinstance(error, discord.app_commands.CommandOnCooldown):
            retry_at = int(time() + error.retry_after)
            msg = f"Slow down, Retry at: <t:{retry_at}:R>"
        elif isinstance(error, discord.app_commands.CheckFailure):
            msg = "You don't have permission to use this command."
        elif isinstance(error, discord.Forbidden):
            log.warning("Forbidden in app command %s: %s", interaction.command, error)
            try:
                msg = "I'm missing permissions in this channel"
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except (discord.HTTPException, discord.Forbidden):
                pass
            return
        else:
            self.last_errors["slash"] = traceback.format_exception(
                type(error), error, error.__traceback__
            )
            log.error("App command error: %r", error)
            msg = "An unexpected error occurred, if this issue persists please contact support."

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # Prefix commands
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: Exception):

        if isinstance(error, commands.CommandInvokeError):
            error = error.original
        
        if isinstance(error, commands.CommandNotFound):
            return
        
        if isinstance(error, commands.BadArgument):
            await ctx.send("Incorrect command arguments, try running them in a different order", delete_after=3)
            return
        
        if isinstance(error, commands.MissingRequiredArgument):
            await ctx.send("Missing command arguments, maybe you forgot a space", delete_after=3)
            return
        
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("You don't have permission to use this command", delete_after=3)
            return
        
        if isinstance(error, commands.CommandOnCooldown):
            if ctx.author.id in _cooldown_notified:
                return
            _cooldown_notified.add(ctx.author.id)
            await ctx.send(f"Try again in {error.retry_after:.1f}s.", delete_after=3)
            await asyncio.sleep(error.retry_after)
            _cooldown_notified.discard(ctx.author.id)
            return
        
        if isinstance(error, commands.BotMissingPermissions):
            await ctx.send("I don't have the required permissions, please contact support", delete_after=3)
            log.warning("Incorrect permissions set")
            return

        if isinstance(error, discord.Forbidden):
            log.warning("Forbidden in %s/%s: %s", ctx.guild, ctx.channel, error)
            try:
                await ctx.send("I'm missing permissions in this channel. Make sure I have **Send Messages** and **Embed Links**.", delete_after=10)
            except discord.Forbidden:
                pass
            return

        self.last_errors["prefix"] = traceback.format_exception(
            type(error), error, error.__traceback__
        )
        log.error("Prefix command error: %r", error)

        await ctx.send("An unexpected error occurred, if this issue persists please contact support", delete_after=3)

    # Events
    @commands.Cog.listener()
    async def on_error(self, event, *args, **kwargs):
        self.last_errors["event"] = traceback.format_exc()
        log.exception("Error in event: %s", event)

    @discord.app_commands.command(name="error", description="Pull the most recent bot error from errorhandlers")
    @is_owner()
    async def lasterror(self, interaction: discord.Interaction):
        embeds = []

        for key, value in self.last_errors.items():
            color = None
            if value:
                text = "".join(value)[-3500:]  # keep under embed limit
                color = discord.Color.red()
            else:
                text = "No errors recorded."
                color = discord.Color.green()

            embed = discord.Embed(
                title=f"Last {key.capitalize()} Error",
                description=f"```py\n{text}\n```",
                color=color
            )

            embeds.append(embed)

        await interaction.response.send_message(embeds=embeds, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ErrorHandler(bot))