import discord
from discord import app_commands
from discord.ext import commands

class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
    
    botGroup = app_commands.Group(
        name="bot",
        description="Bot info and maybe management commands"
    )
    
    @botGroup.command(name="info", description="Show info about the bot")
    @app_commands.checks.cooldown(1, 10)
    async def botinfo(self, interaction: discord.Interaction):
        total_members = 0
        for guild in self.bot.guilds:
            total_members += guild.member_count or 0

        embed = discord.Embed(
            title="Bot info",
            color=discord.Color.fuchsia()
        )
        embed.add_field(
            name="Language",
            value="Python"
        )
        embed.add_field(
            name="Stack",
            value=f"Discord.py {discord.__version__} bot, redis, postgres, aiohttp site"
        )
        embed.add_field(
            name="Support",
            value=self.bot.yaml_config['bot']['support_invite']
        )
        embed.add_field(
            name="Servers",
            value=f"Servers: {len(self.bot.guilds)}, Total Members: {total_members}"
        )

        await interaction.response.send_message(embed=embed)
    
    @commands.command(name="help", description="Bot help")
    @commands.cooldown(1, 10)
    async def helpcmd(self, ctx: commands.Context):
        management_commands = [
            "- `/config view` - View server config",
            "- `/config set` - Set config values",
            "- `/setup` - Full setup guide",
            "- `/partner status` - Shows information on why your server may not be getting partnered"
        ]
        public_commands = [
            "- `/partner loopinfo` - Shows information on the partner loop like time and status",
            "- `/partner ad <guild_id>` - Pull a servers current cached ad message",
            "- `p!ping` - Ping the bot and check status of services",
            "- `p!help` - Get help with commands (this message)"
        ]
        embed = discord.Embed(
            title="Help",
            color=discord.Color.fuchsia()
        )
        embed.add_field(
            name="Management Access",
            value="\n".join(management_commands),
            inline=False
        )
        embed.add_field(
            name="Public Access",
            value="\n".join(public_commands),
            inline=False
        )

        await ctx.reply(embed=embed)

async def setup(bot):
    await bot.add_cog(BotCommands(bot))