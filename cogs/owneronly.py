from redis.asyncio import Redis
from asyncpg import Pool
from discord.ext import commands
from discord import app_commands
from src.checks import is_owner
import discord, json, traceback, textwrap, asyncio

class OwnerOnly(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db_pool: Pool = bot.db_pool
        self.redis: Redis = bot.redis

    serversGroup = app_commands.Group(
        name="servers",
        description="Owner only, Manage servers"
    )

    blacklistGroup = app_commands.Group(
        name="blacklist",
        description="Server blacklist management"
    )

    whitelistGroup = app_commands.Group(
        name="whitelist",
        description="Manage whitelisted links for ad scanning"
    )
    accessGroup = app_commands.Group(
        name="earlyaccess",
        description="Add / remove early access from servers (under 50 members)"
    )

    @accessGroup.command(name="add", description="Assign early access")
    @is_owner()
    async def earlyAccessAdd(self, interaction: discord.Interaction, guild_id: str, user: discord.User, reason: str):
        try:
            iguild_id = int(guild_id)
        except ValueError:
            await interaction.response.send_message("guild_id must be an int", ephemeral=True)
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO early_access (guild_id, user_id, reason) VALUES ($1, $2, $3)"
                " ON CONFLICT (guild_id) DO NOTHING",
                iguild_id, user.id, reason
            )
        await self.redis.sadd("bot:early_access_guilds", iguild_id)
        embed = discord.Embed(
            title="Access granted",
            description=f"`{guild_id}`",
            color=discord.Color.fuchsia()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @accessGroup.command(name="remove", description="Remove early access")
    @is_owner()
    async def earlyAccessRemove(self, interaction: discord.Interaction, guild_id: str):
        try:
            iguild_id = int(guild_id)
        except ValueError:
            await interaction.response.send_message("guild_id must be an int", ephemeral=True)
            return
        async with self.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM early_access WHERE guild_id = $1", iguild_id)
        await self.redis.srem("bot:early_access_guilds", iguild_id)
        await interaction.response.send_message("Early access removed.", ephemeral=True)

    @accessGroup.command(name="list", description="List all early access servers")
    @is_owner()
    async def earlyAccessList(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id, user_id, reason FROM early_access")
        if not rows:
            await interaction.followup.send("No early access servers.", ephemeral=True)
            return
        for i in range(0, len(rows), 25):
            chunk = rows[i:i + 25]
            embed = discord.Embed(
                title=f"Early Access Servers ({i + 1}-{i + len(chunk)} of {len(rows)})",
                color=discord.Color.fuchsia()
            )
            for row in chunk:
                guild = self.bot.get_guild(row["guild_id"])
                guild_name = guild.name if guild else f"Unknown ({row['guild_id']})"
                member_count = guild.member_count if guild else "N/A"
                embed.add_field(
                    name=guild_name,
                    value=f"- Members: {member_count}\n- Reason: {row['reason'] or 'None'}\n- User: <@{row['user_id']}>",
                    inline=False
                )
            await interaction.followup.send(embed=embed, ephemeral=True)


    @blacklistGroup.command(name="add", description="Blacklist a server")
    @is_owner()
    async def addBlacklist(self, interaction: discord.Interaction, guild_id: str, reason: str = "No reason provided"):
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.response.send_message("Guild ID must be a number.", ephemeral=True)
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO blacklists (guild_id, reason, added_by) VALUES ($1, $2, $3)"
                " ON CONFLICT (guild_id) DO UPDATE SET reason = $2, added_by = $3",
                gid, reason, interaction.user.id
            )

        guild = self.bot.get_guild(gid)
        if guild:
            await guild.leave()

        embed = discord.Embed(
            title="Added Blacklist",
            description=f"Reason: {reason}",
            color=discord.Color.fuchsia()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
            
    @blacklistGroup.command(name="remove", description="Remove a blacklist")
    @is_owner()
    async def removeBlacklist(self, interaction: discord.Interaction, guild_id: str):
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.response.send_message("Guild ID must be a number.", ephemeral=True)
            return

        async with self.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM blacklists WHERE guild_id = $1", gid)
        await interaction.response.send_message("Server removed from blacklist", ephemeral=True)
        
    @blacklistGroup.command(name="check", description="Check if a server is blacklisted")
    @is_owner()
    async def checkBlacklist(self, interaction: discord.Interaction, guild_id: str):
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.response.send_message("Guild ID must be a number.", ephemeral=True)
            return

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM blacklists WHERE guild_id = $1", gid)
        if row:
            embed = discord.Embed(
                title="Blacklisted",
                description=f"Reason: {row['reason']}",
                color=discord.Color.fuchsia()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("Not blacklisted", ephemeral=True)

    @whitelistGroup.command(name="add", description="Whitelist a link from ad scanning")
    @is_owner()
    async def addWhitelist(self, interaction: discord.Interaction, link: str):
        async with self.db_pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO whitelisted_links (link, added_by) VALUES ($1, $2)"
                " ON CONFLICT (link) DO NOTHING",
                link, interaction.user.id
            )
        await self.redis.sadd("whitelisted_links", link)
        embed = discord.Embed(
            title="Link Whitelisted",
            description=f"`{link}`",
            color=discord.Color.fuchsia()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @whitelistGroup.command(name="remove", description="Remove a link from the whitelist")
    @is_owner()
    async def removeWhitelist(self, interaction: discord.Interaction, link: str):
        async with self.db_pool.acquire() as conn:
            await conn.execute("DELETE FROM whitelisted_links WHERE link = $1", link)
        await self.redis.srem("whitelisted_links", link)
        await interaction.response.send_message("Link removed from whitelist", ephemeral=True)

    @whitelistGroup.command(name="list", description="List all whitelisted links")
    @is_owner()
    async def listWhitelist(self, interaction: discord.Interaction):
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT link, added_by FROM whitelisted_links")
        if not rows:
            await interaction.response.send_message("No whitelisted links", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"Whitelisted Links ({len(rows)})",
            color=discord.Color.fuchsia()
        )
        for row in rows:
            embed.add_field(name=row["link"], value=f"Added by <@{row['added_by']}>", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

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

            invite_url = None

            if isinstance(partner_channel, discord.TextChannel):
                cache_key = f"invite:{partner_channel.id}"
                invite_url = await self.redis.get(cache_key)
                if not invite_url:
                    try:
                        invites = await partner_channel.invites()
                        invite_url = invites[0].url if invites else (await partner_channel.create_invite(max_age=604800)).url
                        await self.redis.set(cache_key, invite_url, ex=self.bot.yaml_config['cache']['invite'])
                    except discord.Forbidden:
                        pass
                    await asyncio.sleep(self.bot.yaml_config['delays']['invite_fetch'])
            value = (
                f"Members: `{guild.member_count}`\n"
                f"Status: {':green_circle:' if all([config, ad, partner_channel, ad_channel, member_role, partner_ping_role]) else ':red_circle:'}\n"
                f"Invite: {invite_url}"
            )
            fields.append((guild.name, value))
        if not fields:
            await interaction.followup.send(embed=discord.Embed(
                description="No servers.",
                color=discord.Color.fuchsia()
            ), ephemeral=True)
            return

        for i in range(0, max(len(fields), 1), 25):
            chunk = fields[i:i+25]
            embed = discord.Embed(
                title=f"Servers ({i+1}-{i+len(chunk)} of {len(fields)})",
                color=discord.Color.fuchsia()
            )
            for name, value in chunk:
                embed.add_field(name=name, value=value, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

    @serversGroup.command(name="debug")
    @app_commands.describe(server_id="The server to debug")
    @is_owner()
    async def debug_server(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            gid = int(server_id)
        except ValueError:
            await interaction.followup.send("Server ID must be a number.", ephemeral=True)
            return
        guild = self.bot.get_guild(gid)
        if not guild:
            await interaction.followup.send("Guild not found.", ephemeral=True)
            return

        config = await self.bot.config.get(guild.id)
        ad = await self.redis.get(f"ads:{guild.id}")

        # raw ids from config
        partner_channel_id = config.get("partner_channel") if config else None
        ad_channel_id = config.get("ad_channel") if config else None
        member_role_id = config.get("member_role") if config else None
        partner_ping_role_id = config.get("partner_ping_role") if config else None

        # resolved objects
        partner_channel = guild.get_channel(partner_channel_id) if partner_channel_id else None
        ad_channel = guild.get_channel(ad_channel_id) if ad_channel_id else None
        member_role = guild.get_role(member_role_id) if member_role_id else None
        partner_ping_role = guild.get_role(partner_ping_role_id) if partner_ping_role_id else None

        # invite
        invite_url = "N/A"
        if isinstance(partner_channel, discord.TextChannel):
            try:
                invites = await partner_channel.invites()
                invite_url = invites[0].url if invites else (await partner_channel.create_invite(max_age=604800)).url
            except discord.Forbidden:
                invite_url = "Missing permissions"
        elif partner_channel_id and not partner_channel:
            invite_url = "Channel ID set but not resolved"

        def status(val, id_val=None):
            if val:
                return f":green_circle:"
            elif id_val:
                return f":red_circle: (ID `{id_val}` not resolved)"
            return ":red_circle: (not set)"

        embed = discord.Embed(
            title=f"Debug: {guild.name}",
            color=discord.Color.fuchsia()
        )
        embed.add_field(name="Guild", value=(
            f"ID: `{guild.id}`\n"
            f"Members: `{guild.member_count}`\n"
            f"Owner: `{guild.owner}`"
        ), inline=False)

        embed.add_field(name="Config", value=(
            f"Loaded: {':green_circle:' if config else ':red_circle:'}\n"
            f"Raw: ```json\n{json.dumps(config, indent=2) if config else 'None'}```"
        ), inline=False)

        embed.add_field(name="Channels", value=(
            f"Partner Channel: {status(partner_channel, partner_channel_id)} {f'`#{partner_channel.name}`' if partner_channel else ''}\n"
            f"Ad Channel: {status(ad_channel, ad_channel_id)} {f'`#{ad_channel.name}`' if ad_channel else ''}"
        ), inline=False)

        embed.add_field(name="Roles", value=(
            f"Member Role: {status(member_role, member_role_id)} {f'`@{member_role.name}`' if member_role else ''}\n"
            f"Partner Ping Role: {status(partner_ping_role, partner_ping_role_id)} {f'`@{partner_ping_role.name}`' if partner_ping_role else ''}"
        ), inline=False)

        embed.add_field(name="Ad", value=(
            f"Cached: {':green_circle:' if ad else ':red_circle:'}\n"
            f"Content: ```{ad[:200] if ad else 'None'}```"
        ), inline=False)

        embed.add_field(name="Invite", value=invite_url, inline=False)

        overall = all([config, ad, partner_channel, ad_channel, member_role, partner_ping_role])
        embed.add_field(name="Overall Status", value=':green_circle: Ready' if overall else ':red_circle: Not ready', inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @serversGroup.command(name="debugall")
    @is_owner()
    async def debug_all_servers(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            ad = await self.redis.get(f"ads:{guild.id}")

            partner_channel_id = config.get("partner_channel") if config else None
            ad_channel_id = config.get("ad_channel") if config else None
            member_role_id = config.get("member_role") if config else None
            partner_ping_role_id = config.get("partner_ping_role") if config else None

            partner_channel = guild.get_channel(partner_channel_id) if partner_channel_id else None
            ad_channel = guild.get_channel(ad_channel_id) if ad_channel_id else None
            member_role = guild.get_role(member_role_id) if member_role_id else None
            partner_ping_role = guild.get_role(partner_ping_role_id) if partner_ping_role_id else None

            invite_url = "N/A"
            if isinstance(partner_channel, discord.TextChannel):
                cache_key = f"invite:{partner_channel.id}"
                invite_url = await self.redis.get(cache_key)
                if not invite_url:
                    try:
                        invites = await partner_channel.invites()
                        invite_url = invites[0].url if invites else (await partner_channel.create_invite(max_age=604800)).url
                        await self.redis.set(cache_key, invite_url, ex=self.bot.yaml_config['cache']['invite'])
                    except discord.Forbidden:
                        invite_url = "Missing permissions"
                    await asyncio.sleep(self.bot.yaml_config['delays']['invite_fetch'])
            elif partner_channel_id and not partner_channel:
                invite_url = "Channel ID set but not resolved"

            def status(val, id_val=None):
                if val:
                    return ":green_circle:"
                elif id_val:
                    return f":red_circle: (ID `{id_val}` not resolved)"
                return ":red_circle: (not set)"

            overall = all([config, ad, partner_channel, ad_channel, member_role, partner_ping_role])

            embed = discord.Embed(
                title=f"{':green_circle:' if overall else ':red_circle:'} {guild.name}",
                color=discord.Color.green() if overall else discord.Color.red()
            )
            embed.add_field(name="Guild", value=(
                f"ID: `{guild.id}`\n"
                f"Members: `{guild.member_count}`\n"
                f"Owner: `{guild.owner}`"
            ), inline=False)

            embed.add_field(name="Config", value=(
                f"Loaded: {':green_circle:' if config else ':red_circle:'}\n"
                f"Raw: ```json\n{json.dumps(config, indent=2) if config else 'None'}```"
            ), inline=False)

            embed.add_field(name="Channels", value=(
                f"Partner Channel: {status(partner_channel, partner_channel_id)} {f'`#{partner_channel.name}`' if partner_channel else ''}\n"
                f"Ad Channel: {status(ad_channel, ad_channel_id)} {f'`#{ad_channel.name}`' if ad_channel else ''}"
            ), inline=False)

            embed.add_field(name="Roles", value=(
                f"Member Role: {status(member_role, member_role_id)} {f'`@{member_role.name}`' if member_role else ''}\n"
                f"Partner Ping Role: {status(partner_ping_role, partner_ping_role_id)} {f'`@{partner_ping_role.name}`' if partner_ping_role else ''}"
            ), inline=False)

            embed.add_field(name="Ad", value=(
                f"Cached: {':green_circle:' if ad else ':red_circle:'}\n"
                f"Content: ```{ad[:200] if ad else 'None'}```"
            ), inline=False)

            embed.add_field(name="Invite", value=invite_url, inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)

    @serversGroup.command(name="leave")
    @app_commands.describe(server_id="The server to leave")
    @is_owner()
    async def leave_server(self, interaction: discord.Interaction, server_id: str):
        await interaction.response.defer(ephemeral=True)

        try:
            gid = int(server_id)
        except ValueError:
            await interaction.followup.send("Server ID must be a number.", ephemeral=True)
            return
        guild = self.bot.get_guild(gid)
        if not guild:
            await interaction.followup.send("Guild not found.", ephemeral=True)
            return

        await interaction.followup.send(f"Leaving **{guild.name}** (`{guild.id}`).", ephemeral=True)
        await guild.leave()

    @serversGroup.command(name="cooldowns", description="Show next eligible partner time for every server")
    @is_owner()
    async def server_cooldowns(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ver = self.bot.yaml_config['cache']['cache_version']
        default_delay = self.bot.yaml_config['partner_delay']['default']
        guilds = list(self.bot.guilds)

        async with self.redis.pipeline(transaction=False) as pipe:
            for guild in guilds:
                pipe.get(f"{ver}:server_last_partner:{guild.id}")
            last_values = await pipe.execute()

        lines = []
        for guild, last in zip(guilds, last_values):
            config = await self.bot.config.get(guild.id)
            partner_delay = (config.get("partner_delay") if config else None) or default_delay
            if last is None:
                lines.append(f"**{guild.name}**: eligible now")
            else:
                eligible_ts = int(float(last) + partner_delay)
                lines.append(f"**{guild.name}**: <t:{eligible_ts}:f> (<t:{eligible_ts}:R>)")

        if not lines:
            await interaction.followup.send("No servers.", ephemeral=True)
            return

        for i in range(0, len(lines), 20):
            chunk = lines[i:i + 20]
            embed = discord.Embed(
                title=f"Partner Cooldowns ({i + 1}-{i + len(chunk)} of {len(lines)})",
                description="\n".join(chunk),
                color=discord.Color.fuchsia()
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

    @commands.command(name="exec")
    @commands.is_owner()
    async def exec_code(self, ctx: commands.Context, *, code: str):
        env = {
            "bot": self.bot,
            "ctx": ctx,
            "discord": discord,
            "asyncio": asyncio,
            "db_pool": getattr(self.bot, "db_pool", None),
            "guild": ctx.guild,
            "channel": ctx.channel,
            "author": ctx.author,
            "message": ctx.message
        }

        try:
            func_code = f"async def _exec():\n{textwrap.indent(code, "    ")}"

            exec(func_code, env)
            await env["_exec"]()
        except Exception:
            error = traceback.format_exc()

            lines = error.strip().splitlines()
            tb_body = "\n".join(lines[:-1])
            exc_line = lines[-1]

            embed = discord.Embed(
                title="Exec exception",
                color=discord.Color.fuchsia()
            )
            
            embed.add_field(name="Output", value=f"```\n{tb_body}\n```", inline=False)
            embed.add_field(name="Error", value=f"```\n{exc_line}\n```", inline=False)

            await ctx.send(embed=embed)
            return

async def setup(bot: commands.Bot):
    await bot.add_cog(OwnerOnly(bot))