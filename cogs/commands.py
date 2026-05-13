import discord
from discord import app_commands
from discord.ext import commands, tasks

class BotCommands(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.Bot = bot
    
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
            "- `/partner reqs <membercount>` - Show partner reqs scaled to a membercount",
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

    @commands.command(name="support", description="Get the support server invite")
    async def support(self, ctx: commands.Context):
        await ctx.reply(self.bot.yaml_config['bot']['support_invite'])

    @tasks.loop(minutes=5)
    async def userloop(self):
        support_guild = self.bot.get_guild(self.bot.yaml_config['bot']['support_guild'])
        if not support_guild:
            return
        role = support_guild.get_role(self.bot.yaml_config['roles']['bot_user'])
        if not role:
            return
        owner_ids = {g.owner_id for g in self.bot.guilds if g.owner_id}
        for member in list(role.members):
            if member.id not in owner_ids:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    pass
        for owner_id in owner_ids:
            member = support_guild.get_member(owner_id)
            if member and role not in member.roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    pass
    @userloop.before_loop
    async def before_five_minute_loop(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        self.userloop.start()

    async def cog_unload(self):
        self.userloop.cancel()

async def setup(bot):
    await bot.add_cog(BotCommands(bot))