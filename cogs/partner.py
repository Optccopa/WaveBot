from discord.ext import tasks, commands
from src.checks import is_owner, is_management
from src.prompts import SCAN_PROMPT, RULE_PATTERNS
from anthropic import AsyncAnthropic, APIStatusError
from redis.asyncio import Redis
from asyncpg import Pool, UniqueViolationError
from main import Bot
import discord, random, logging, asyncio, re, os, hashlib, json, time, yaml

from src.constants import ALL_PINGS

LINK_REGEX = re.compile(r"https?://\S+")
PING_RE = re.compile(r"@everyone|@here|<@&\d+>")

with open("config.yaml", "r") as f:
    YAML_CONFIG = yaml.safe_load(f)

logger = logging.getLogger(__name__)


async def _interaction_error_reply(interaction: discord.Interaction, content: str):
    try:
        if interaction.response.is_done():
            await interaction.followup.send(content, ephemeral=True)
        else:
            await interaction.response.send_message(content, ephemeral=True)
    except discord.HTTPException:
        pass


async def fetch_partnership(bot, partnership_id: int) -> dict | None:
    cache_key = f"partner_info:{partnership_id}"
    cached = await bot.redis.get(cache_key)
    if cached == "0":
        return None
    if cached:
        return json.loads(cached)
    async with bot.db_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM partnerships WHERE id = $1", partnership_id
        )
    if row is None:
        await bot.redis.set(cache_key, "0", ex=86400)
        return None
    info = dict(row)
    info["partnered_at"] = info["partnered_at"].isoformat()
    # default=str so future timestamp/numeric columns degrade to strings instead
    # of failing every cache write (and therefore every button click)
    await bot.redis.set(cache_key, json.dumps(info, default=str), ex=2592000)
    return info


class PartnerInfoButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wavebot:partner_info:(?P<pid>\d+)",
):
    def __init__(self, partnership_id: int):
        super().__init__(
            discord.ui.Button(
                label="Partner Info",
                style=discord.ButtonStyle.gray,
                custom_id=f"wavebot:partner_info:{partnership_id}",
            )
        )
        self.partnership_id: int = partnership_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        return cls(int(match["pid"]))

    async def callback(self, interaction: discord.Interaction):
        logger.info(
            "Partner info clicked by user: %s guild: %s partnership: %d",
            interaction.user.name,
            interaction.guild.name if interaction.guild else None,
            self.partnership_id,
        )
        bot = interaction.client

        allowed = await bot.redis.set(
            f"cooldown:partner_info:{interaction.user.id}", "1", nx=True, ex=10
        )
        if not allowed:
            await interaction.response.send_message("Slow down.", ephemeral=True)
            return

        try:
            info = await fetch_partnership(bot, self.partnership_id)
        except Exception:
            logger.exception(
                "partner info lookup failed for partnership %d", self.partnership_id
            )
            await _interaction_error_reply(
                interaction, "Something went wrong. Please try again later."
            )
            return
        if info is None:
            await interaction.response.send_message(
                "Partner not found.", ephemeral=True
            )
            return

        host_id = info.get("host_guild_id")
        viewer_id = interaction.guild.id if interaction.guild else None
        embed = discord.Embed(title="Partner Info", color=discord.Color.fuchsia())
        for n in (1, 2):
            gid = info[f"guild{n}_id"]
            tags = []
            if gid == viewer_id:
                tags.append("this server")
            if gid == host_id:
                tags.append("host")
            tag_str = f" ({', '.join(tags)})" if tags else ""
            # guild{n}_ping fires in guild{n}'s own partner channel (announcing the other side's ad)
            ping_label = "Pinged here" if gid == viewer_id else "Pinged there"
            embed.add_field(
                name=f"{info[f'guild{n}_name']}{tag_str}",
                value=f"Guild ID: `{gid}`\nMembers: `{info[f'guild{n}_members']}`\n{ping_label}: `{info[f'guild{n}_ping']}`",
                inline=True,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ReportModal(discord.ui.Modal, title="Report Server (In testing)"):
    category = discord.ui.Label(
        text="Category",
        component=discord.ui.Select(
            placeholder="Pick a category",
            options=[
                discord.SelectOption(label="Scamming"),
                discord.SelectOption(label="IRL trading"),
                discord.SelectOption(label="Botted"),
                discord.SelectOption(label="Non DonutSMP based"),
                discord.SelectOption(label="Other"),
            ],
        ),
    )

    reason = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.short,
        placeholder="Why are you reporting this server?",
        max_length=1000,
    )

    rule = discord.ui.TextInput(
        label="Rule broken",
        style=discord.TextStyle.paragraph,
        placeholder="What rule does this server's advertisement or behavior break?",
        max_length=1000,
    )

    def __init__(self, partnership_id: int, reported_gid: int, reported_name: str):
        super().__init__()
        self.partnership_id = partnership_id
        self.reported_gid = reported_gid
        self.reported_name = reported_name

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "report modal failed (partnership %d)",
            self.partnership_id,
            exc_info=error,
        )
        await _interaction_error_reply(
            interaction,
            "Something went wrong submitting your report. Please try again later.",
        )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        bot = interaction.client
        dedupe_key = f"reported:{self.partnership_id}:{interaction.user.id}"
        if await bot.redis.exists(dedupe_key):
            await interaction.followup.send(
                "You already reported this partnership.", ephemeral=True
            )
            return

        category = self.category.component.values[0]
        try:
            async with bot.db_pool.acquire() as conn:
                report_id = await conn.fetchval(
                    """INSERT INTO reports
                       (partnership_id, reporter_id, reporter_guild_id, reported_guild_id, category, reason, evidence)
                       VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING id""",
                    self.partnership_id,
                    interaction.user.id,
                    interaction.guild.id if interaction.guild else None,
                    self.reported_gid,
                    category,
                    self.reason.value,
                    self.rule.value,
                )
        except UniqueViolationError:
            await bot.redis.set(dedupe_key, "1", ex=2592000)
            await interaction.followup.send(
                "You already reported this partnership.", ephemeral=True
            )
            return
        # dedupe key only after the insert succeeds — a failed insert must not lock the user out
        await bot.redis.set(dedupe_key, "1", ex=2592000)

        embed = discord.Embed(
            title=f"Report #{report_id} - {category}", color=discord.Color.red()
        )
        embed.add_field(
            name="Reported server",
            value=f"{self.reported_name} (`{self.reported_gid}`)",
            inline=False,
        )
        embed.add_field(
            name="Reporter",
            value=f"{interaction.user} (`{interaction.user.id}`) in {interaction.guild.name if interaction.guild else '?'}",
            inline=False,
        )
        embed.add_field(name="Reason", value=self.reason.value[:1024], inline=False)
        embed.add_field(name="Rule broken", value=self.rule.value[:1024], inline=False)
        ad = await bot.redis.get(f"ads:{self.reported_gid}")
        if ad:
            embed.add_field(name="Current ad", value=ad[:1024], inline=False)
        embed.set_footer(text=f"Partnership #{self.partnership_id}")

        channel = bot.get_channel(YAML_CONFIG["channels"]["reports"])
        if channel:
            view = discord.ui.View(timeout=None)
            view.add_item(ReportBlacklistButton(report_id, self.reported_gid))
            view.add_item(ReportDismissButton(report_id))
            try:
                await channel.send(embed=embed, view=view)
            except discord.HTTPException as e:
                logger.error(
                    "failed posting report #%d to reports channel: %s", report_id, e
                )
        else:
            logger.error(
                "reports channel %s not found", YAML_CONFIG["channels"]["reports"]
            )
        await interaction.followup.send(
            f"Report submitted, Beyond obvious rule violations you should make a ticket in our [support server]({YAML_CONFIG['bot']['support_invite']}) and show proof",
            ephemeral=True,
        )


class ReportButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wavebot:report:(?P<pid>\d+)",
):
    def __init__(self, partnership_id: int):
        super().__init__(
            discord.ui.Button(
                label="Report",
                style=discord.ButtonStyle.red,
                custom_id=f"wavebot:report:{partnership_id}",
            )
        )
        self.partnership_id: int = partnership_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        return cls(int(match["pid"]))

    async def callback(self, interaction: discord.Interaction):
        logger.info(
            "Report clicked by user: %s guild: %s partnership: %d",
            interaction.user.name,
            interaction.guild.name if interaction.guild else None,
            self.partnership_id,
        )
        bot = interaction.client
        allowed = await bot.redis.set(
            f"cooldown:report:{interaction.user.id}", "1", nx=True, ex=10
        )
        if not allowed:
            await interaction.response.send_message("Slow down.", ephemeral=True)
            return

        if await bot.redis.exists(
            f"reported:{self.partnership_id}:{interaction.user.id}"
        ):
            await interaction.response.send_message(
                "You already reported this partnership.", ephemeral=True
            )
            return

        try:
            info = await fetch_partnership(bot, self.partnership_id)
        except Exception:
            logger.exception(
                "report lookup failed for partnership %d", self.partnership_id
            )
            await _interaction_error_reply(
                interaction, "Something went wrong. Please try again later."
            )
            return
        if info is None:
            await interaction.response.send_message(
                "Partner not found.", ephemeral=True
            )
            return

        viewer_id = interaction.guild.id if interaction.guild else None
        if viewer_id == info["guild1_id"]:
            reported_gid, reported_name = info["guild2_id"], info["guild2_name"]
        elif viewer_id == info["guild2_id"]:
            reported_gid, reported_name = info["guild1_id"], info["guild1_name"]
        else:
            await interaction.response.send_message(
                "Could not determine which server to report.", ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ReportModal(self.partnership_id, reported_gid, reported_name)
        )


class ReportActionModal(discord.ui.Modal):
    note = discord.ui.TextInput(
        label="Reason",
        style=discord.TextStyle.paragraph,
        placeholder="Sent to the reporter in DMs.",
        max_length=1000,
    )

    def __init__(self, action: str, report_id: int, guild_id: int | None = None):
        # action: "blacklisted" or "dismissed"; guild_id only needed for blacklist
        label = "Blacklist" if action == "blacklisted" else "Dismiss"
        super().__init__(title=f"{label} report #{report_id}")
        self.action = action
        self.report_id = report_id
        self.guild_id = guild_id

    async def on_error(self, interaction: discord.Interaction, error: Exception):
        logger.error(
            "report action modal failed (report #%d)", self.report_id, exc_info=error
        )
        await _interaction_error_reply(
            interaction, "Something went wrong. Please try again."
        )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        bot = interaction.client

        try:
            async with bot.db_pool.acquire() as conn:
                async with conn.transaction():
                    row = await conn.fetchrow(
                        "UPDATE reports SET status = $1, handled_by = $2, handled_reason = $3"
                        " WHERE id = $4 AND status = 'open'"
                        " RETURNING partnership_id, reporter_id, reported_guild_id",
                        self.action,
                        interaction.user.id,
                        self.note.value,
                        self.report_id,
                    )
                    if row is not None and self.action == "blacklisted":
                        await conn.execute(
                            "INSERT INTO blacklists (guild_id, reason, added_by) VALUES ($1, $2, $3)"
                            " ON CONFLICT (guild_id) DO UPDATE SET reason = $2, added_by = $3",
                            self.guild_id,
                            f"Report #{self.report_id}: {self.note.value[:200]}",
                            interaction.user.id,
                        )
        except Exception:
            logger.exception(
                "%s action failed for report #%d", self.action, self.report_id
            )
            await _interaction_error_reply(
                interaction, "Something went wrong. Please try again."
            )
            return
        if row is None:
            await interaction.followup.send(
                "This report was already handled.", ephemeral=True
            )
            return

        if self.action == "blacklisted" and row["partnership_id"] is not None:
            await bot.redis.delete(f"partner_info:{row['partnership_id']}")

        logger.info(
            "Report #%d %s by %s", self.report_id, self.action, interaction.user.name
        )

        label = "Blacklisted" if self.action == "blacklisted" else "Dismissed"
        if interaction.message:
            embeds = interaction.message.embeds
            embed = (
                embeds[0]
                if embeds
                else discord.Embed(title=f"Report #{self.report_id}")
            )
            embed.colour = discord.Color.dark_grey()
            embed.add_field(
                name="Handled",
                value=f"{label} by {interaction.user} (`{interaction.user.id}`)\nReason: {self.note.value[:900]}",
                inline=False,
            )
            try:
                await interaction.message.edit(embed=embed, view=None)
            except discord.HTTPException as e:
                logger.error(
                    "failed editing report message for #%d: %s", self.report_id, e
                )

        try:
            reporter = bot.get_user(row["reporter_id"]) or await bot.fetch_user(
                row["reporter_id"]
            )
            outcome = (
                f"actioned, `{row['reported_guild_id']} has been blacklisted from wavebot`"
                if self.action == "blacklisted"
                else "dismissed"
            )
            await reporter.send(
                f"Your report against guild `{row['reported_guild_id']}` was {outcome}.\n"
                f"Note: {self.note.value}"
            )
        except discord.HTTPException as e:
            logger.warning(
                "could not DM reporter %d for report #%d: %s",
                row["reporter_id"],
                self.report_id,
                e,
            )

        if self.action == "blacklisted":
            guild = bot.get_guild(self.guild_id)
            if guild:
                try:
                    await guild.leave()
                except discord.HTTPException as e:
                    logger.error(
                        "failed leaving blacklisted guild %d: %s", self.guild_id, e
                    )

        await interaction.followup.send(
            f"Report #{self.report_id} {self.action}.", ephemeral=True
        )


class ReportBlacklistButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wavebot:report_bl:(?P<rid>\d+):(?P<gid>\d+)",
):
    def __init__(self, report_id: int, guild_id: int):
        super().__init__(
            discord.ui.Button(
                label="Blacklist",
                style=discord.ButtonStyle.red,
                custom_id=f"wavebot:report_bl:{report_id}:{guild_id}",
            )
        )
        self.report_id: int = report_id
        self.guild_id: int = guild_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        return cls(int(match["rid"]), int(match["gid"]))

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        if not await bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "You don't have permission to do that.", ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ReportActionModal("blacklisted", self.report_id, self.guild_id)
        )


class ReportDismissButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"wavebot:report_dm:(?P<rid>\d+)",
):
    def __init__(self, report_id: int):
        super().__init__(
            discord.ui.Button(
                label="Dismiss",
                style=discord.ButtonStyle.gray,
                custom_id=f"wavebot:report_dm:{report_id}",
            )
        )
        self.report_id: int = report_id

    @classmethod
    async def from_custom_id(
        cls,
        interaction: discord.Interaction,
        item: discord.ui.Button,
        match: re.Match[str],
    ):
        return cls(int(match["rid"]))

    async def callback(self, interaction: discord.Interaction):
        bot = interaction.client
        if not await bot.is_owner(interaction.user):
            await interaction.response.send_message(
                "You don't have permission to do that.", ephemeral=True
            )
            return

        await interaction.response.send_modal(
            ReportActionModal("dismissed", self.report_id)
        )


class AddBotView(discord.ui.View):
    def __init__(self, partnership_id: int | None = None):
        super().__init__(timeout=None)
        if partnership_id is not None:
            self.add_item(PartnerInfoButton(partnership_id))
            self.add_item(ReportButton(partnership_id))

    @discord.ui.button(
        label="Add WaveBot",
        style=discord.ButtonStyle.blurple,
        custom_id="wavebot:add_bot",
    )
    async def add_bot(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ):
        logger.info(
            "Add bot view clicked by user: %s guild: %s",
            interaction.user.name,
            interaction.guild.name,
        )
        embed = discord.Embed(
            title="Add WaveBot!",
            description="WaveBot automatically does partners with other servers without any fuss",
            color=discord.Color.fuchsia(),
        )
        embed.add_field(
            name="Get Started",
            value=f"[Invite WaveBot]({YAML_CONFIG['bot']['bot_invite']}) then run `/config set` for setup",
            inline=False,
        )
        embed.add_field(
            name="Need Help?",
            value=f"[Join the support server]({YAML_CONFIG['bot']['support_invite']}) (Reccomended)",
            inline=False,
        )
        await interaction.response.send_message(
            YAML_CONFIG["bot"]["support_invite"], embed=embed, ephemeral=True
        )


def get_req(count_a: int, count_b: int) -> dict:
    count_a = count_a or 0
    count_b = count_b or 0
    if count_a >= count_b:
        host, guest = count_a, count_b
        a_is_host = True
    else:
        host, guest = count_b, count_a
        a_is_host = False
    config_req = YAML_CONFIG["partner_requirements"]
    scale = host / config_req["scale"]
    tiers = [
        (round(config_req["below_do_none"] * scale), "none"),
        (round(config_req["below_do_partner"] * scale), "partner"),
        (round(config_req["below_do_here"] * scale), "here"),
        (round(config_req["below_do_partnerhere"] * scale), "partnerhere"),
        (float("inf"), "member"),
    ]
    ping_a, ping_b = "none", "none"

    for ceiling, host_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, "member"
            else:
                ping_a, ping_b = "member", host_ping
            logger.debug(
                "scale: %.3f ceiling: %s -> host_ping: %s", scale, ceiling, host_ping
            )
            break

    result = {
        "server_a": ping_a,
        "server_b": ping_b,
        "host": "server_a" if a_is_host else "server_b",
    }
    return result


class Partner(commands.Cog):
    def __init__(self, bot):
        self.bot: Bot = bot
        self.redis: Redis = bot.redis
        self.db_pool: Pool = bot.db_pool
        self._partner_lock = asyncio.Lock()
        self._scan_semaphore = asyncio.Semaphore(3)
        self.client: AsyncAnthropic = AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    partnerGroup = discord.app_commands.Group(
        name="partner", description="Partner commands"
    )

    async def parse_ping(self, guild_id: int, ping: str = "none") -> str:
        config = await self.bot.config.get(guild_id)

        if ping == "member":
            return f"<@&{config.get('member_role')}>"

        elif ping == "partner":
            return f"<@&{config.get('partner_ping_role')}>"

        elif ping == "here":
            return "@here"

        elif ping == "partnerhere":
            return f"@here <@&{config.get('partner_ping_role')}>"
        else:  # none
            return ""

    async def has_cooldown(self, a: int, b: int) -> bool:
        key = f"{self.bot.yaml_config['cache']['cache_version']}:partner_cooldown:{min(a, b)}:{max(a, b)}"
        result = bool(await self.redis.exists(key))
        logger.debug("%s -> %s", key, "HIT" if result else "MISS")
        return result

    async def set_cooldown(self, a: int, b: int):
        key = f"{self.bot.yaml_config['cache']['cache_version']}:partner_cooldown:{min(a, b)}:{max(a, b)}"
        await self.redis.set(
            key, 1, ex=self.bot.yaml_config["cache"]["partner_cooldown"]
        )
        logger.debug("SET %s (7d)", key)

    async def set_server_last_partner(self, guild_id: int):
        ver = self.bot.yaml_config["cache"]["cache_version"]
        ttl = self.bot.yaml_config["partner_delay"]["max"]
        await self.redis.set(
            f"{ver}:server_last_partner:{guild_id}", str(time.time()), ex=ttl
        )

    async def get_server_last_partner(self, guild_id: int) -> float | None:
        ver = self.bot.yaml_config["cache"]["cache_version"]
        val = await self.redis.get(f"{ver}:server_last_partner:{guild_id}")
        return float(val) if val else None

    async def _can_warn(self, guild_id: int, warn_key: str, ttl: int = 21600) -> bool:
        ver = self.bot.yaml_config["cache"]["cache_version"]
        return bool(
            await self.redis.set(
                f"{ver}:warn:{warn_key}:{guild_id}", 1, nx=True, ex=ttl
            )
        )

    async def validate_server(
        self, guild: discord.Guild, config: dict | None = None
    ) -> str | None:
        if config is None:
            config = await self.bot.config.get(guild.id)
        if not config:
            return "No configuration found"
        reqs = self.bot.yaml_config["requirements"]

        member_role = guild.get_role(config.get("member_role"))
        partner_role = guild.get_role(config.get("partner_ping_role"))
        partner_channel = guild.get_channel(config.get("partner_channel"))

        if not member_role:
            return "Member role not configured"
        if not partner_role:
            return "Partner role not configured"
        if not partner_channel:
            return "Partner channel not configured"

        total = guild.member_count or 1
        min_member = reqs["member_role_min_coverage"]
        min_visible = reqs["channel_visibility_min"]
        min_partner = reqs["partner_role_min_coverage"]

        member_pct = len(member_role.members) / total
        if member_pct < min_member:
            return f"Less than {round(min_member * 100)}% of server members have the member role, make sure your member role is assigned to everyone"

        if not partner_channel.permissions_for(member_role).view_channel:
            return f"Less than {round(min_visible * 100)}% of members can see the partner channel, make sure your partner channel is visible to everyone"

        partner_pct = len(partner_role.members) / total
        if partner_pct < min_partner:
            return f"Less than {round(min_partner * 100)}% of members have the partner ping role"

        return None

    async def match_servers(
        self, guilds: list[tuple[int, int]]
    ) -> tuple[list[tuple[int, int]], list[int]]:
        member_counts = {gid: mc for gid, mc in guilds}
        pool = list(member_counts)
        random.shuffle(pool)  # randomise before sort so ties break randomly

        if len(pool) < 2:
            return [], pool

        ver = self.bot.yaml_config["cache"]["cache_version"]
        all_pairs = [
            (min(a, b), max(a, b)) for i, a in enumerate(pool) for b in pool[i + 1 :]
        ]

        # Fetch cooldowns + premium configs in one pipeline round-trip
        async with self.redis.pipeline(transaction=False) as pipe:
            for a, b in all_pairs:
                pipe.exists(f"{ver}:partner_cooldown:{a}:{b}")
            for gid in pool:
                pipe.get(f"premium:{gid}")
            results = await pipe.execute()

        on_cooldown = {
            pair for pair, hit in zip(all_pairs, results[: len(all_pairs)]) if hit
        }
        logger.debug(
            "[match] cooldown check: %d/%d pairs blocked",
            len(on_cooldown),
            len(all_pairs),
        )

        # Parse premium configs — DB fallback for cache misses
        # "0" sentinel = confirmed non-premium (negative cache)
        prem_configs: dict[int, dict] = {}
        miss_ids = []
        corrupt_keys = []
        for gid, val in zip(pool, results[len(all_pairs) :]):
            if val:
                if val == "0":
                    continue
                try:
                    prem_configs[gid] = json.loads(val)
                except (json.JSONDecodeError, ValueError):
                    corrupt_keys.append(f"premium:{gid}")
                    miss_ids.append(gid)
            else:
                miss_ids.append(gid)

        if corrupt_keys:
            async with self.redis.pipeline(transaction=False) as pipe:
                for key in corrupt_keys:
                    pipe.delete(key)
                await pipe.execute()

        if miss_ids:
            async with self.db_pool.acquire() as conn:
                rows = await conn.fetch(
                    "SELECT * FROM premium WHERE guild_id = ANY($1::bigint[])", miss_ids
                )
            found_ids: set[int] = set()
            async with self.redis.pipeline(transaction=False) as pipe:
                for row in rows:
                    data = dict(row)
                    data["added_at"] = (
                        data["added_at"].isoformat() if data.get("added_at") else None
                    )
                    prem_configs[row["guild_id"]] = data
                    found_ids.add(row["guild_id"])
                    pipe.set(f"premium:{row['guild_id']}", json.dumps(data), ex=2592000)
                for gid in miss_ids:
                    if gid not in found_ids:
                        pipe.set(f"premium:{gid}", "0", ex=3600)
                await pipe.execute()

        # Build adjacency — skip pairs on cooldown or blocked by premium ping restrictions
        # Empty available_pings defaults to all pings allowed
        neighbors: dict[int, set[int]] = {s: set() for s in pool}
        for a, b in all_pairs:
            if (a, b) in on_cooldown:
                continue
            if a in prem_configs or b in prem_configs:
                r = get_req(member_counts[a], member_counts[b])
                ping_blocked = False
                for gid, ping_key in ((a, "server_a"), (b, "server_b")):
                    if gid in prem_configs:
                        allowed = prem_configs[gid].get("available_pings") or ALL_PINGS
                        if r[ping_key] not in allowed:
                            logger.debug(
                                "[match] pair (%d,%d) blocked: %d premium, ping '%s' not in %s",
                                a,
                                b,
                                gid,
                                r[ping_key],
                                allowed,
                            )
                            ping_blocked = True
                            break
                if ping_blocked:
                    continue
            neighbors[a].add(b)
            neighbors[b].add(a)

        # Greedy maximum matching — most-constrained nodes first
        # Picking the partner with the fewest remaining options keeps the graph
        # denser for subsequent nodes, approaching optimal without Blossom complexity.
        order = sorted(pool, key=lambda x: len(neighbors[x]))
        matched: set[int] = set()
        pairs: list[tuple[int, int]] = []

        for server in order:
            if server in matched:
                continue
            available = [p for p in neighbors[server] if p not in matched]
            if not available:
                continue
            partner = min(available, key=lambda x: len(neighbors[x] - matched))
            pairs.append((server, partner))
            matched.add(server)
            matched.add(partner)

        sat_out = [s for s in pool if s not in matched]
        logger.debug("result: %d pairs, %d sat out", len(pairs), len(sat_out))
        for a, b in pairs:
            logger.debug("paired %d <-> %d", a, b)
        for s in sat_out:
            logger.debug(
                "sat out or all on cooldown: %s",
                self.bot.get_guild(s).name
                if self.bot.get_guild(s)
                else f"Guild not found: {s}",
            )
        return pairs, sat_out

    async def partner(self, server1_id: int, server2_id: int):
        logger.debug("starting partner %d <-> %d", server1_id, server2_id)

        config1 = await self.bot.config.get(server1_id)
        config2 = await self.bot.config.get(server2_id)
        if not config1 or not config2:
            logger.warning(
                "abort %d<->%d: missing config (config1=%s config2=%s)",
                server1_id,
                server2_id,
                bool(config1),
                bool(config2),
            )
            return None, None

        guild1: discord.Guild = self.bot.get_guild(server1_id)
        guild2: discord.Guild = self.bot.get_guild(server2_id)
        if not guild1 or not guild2:
            logger.warning(
                "abort %d<->%d: guild not in cache (guild1=%s guild2=%s)",
                server1_id,
                server2_id,
                bool(guild1),
                bool(guild2),
            )
            return None, None

        logger.debug(
            "guilds resolved: %s (%d members) <-> %s (%d members)",
            guild1.name,
            guild1.member_count,
            guild2.name,
            guild2.member_count,
        )

        channel1 = guild1.get_channel(config1.get("partner_channel"))
        channel2 = guild2.get_channel(config2.get("partner_channel"))
        if not channel1 or not channel2:
            logger.warning(
                "abort %d<->%d: channel not found (ch1=%s ch2=%s)",
                server1_id,
                server2_id,
                bool(channel1),
                bool(channel2),
            )
            return None, None
        logger.debug(
            "channels resolved: #%s (%d) <-> #%s (%d)",
            getattr(channel1, "name", None),
            server1_id,
            getattr(channel2, "name", None),
            server2_id,
        )

        r = get_req(guild1.member_count, guild2.member_count)
        ping_a = r.get("server_a", "none")
        ping_b = r.get("server_b", "none")
        if ping_a is None or ping_b is None:
            logger.warning(
                "abort %d<->%d: get_req returned incomplete pings",
                server1_id,
                server2_id,
            )
            return None, None
        logger.debug(
            "%d(%d) pings %s | %d(%d) pings %s | host: %s",
            server1_id,
            guild1.member_count,
            ping_a,
            server2_id,
            guild2.member_count,
            ping_b,
            r.get("host"),
        )

        raw_ad1 = await self.redis.get(f"ads:{server1_id}")
        raw_ad2 = await self.redis.get(f"ads:{server2_id}")
        if not raw_ad1 or not raw_ad2:
            logger.warning(
                "abort %d<->%d: missing ad (ad1=%s ad2=%s)",
                server1_id,
                server2_id,
                bool(raw_ad1),
                bool(raw_ad2),
            )
            return None, None

        if self.bot.yaml_config["bot"]["send_pings"] == True:
            ad1 = f"{raw_ad1}\n\n{await self.parse_ping(server2_id, ping_b)}"
            ad2 = f"{raw_ad2}\n\n{await self.parse_ping(server1_id, ping_a)}"
        else:
            logger.debug("send_pings is False, sending ads without pings")
            ad1 = f"{raw_ad1}\n\nPlaceholder for {ping_b}"
            ad2 = f"{raw_ad2}\n\nPlaceholder for {ping_a}"

        logger.debug(
            "ad lengths: server1_ad=%d server2_ad=%d (ad1 sent to ch2, ad2 sent to ch1)",
            len(ad1),
            len(ad2),
        )
        if len(ad1) > 2000 or len(ad2) > 2000:
            logger.warning(
                "abort: ad too long - server1_ad=%d server2_ad=%d (max 2000)",
                len(ad1),
                len(ad2),
            )
            return None, None

        host_guild_id = server1_id if r.get("host") == "server_a" else server2_id
        async with self.db_pool.acquire() as conn:
            partnership_id = await conn.fetchval(
                """INSERT INTO partnerships
                   (guild1_id, guild2_id, guild1_name, guild2_name, guild1_members, guild2_members, guild1_ping, guild2_ping, host_guild_id)
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9) RETURNING id""",
                server1_id,
                server2_id,
                guild1.name,
                guild2.name,
                guild1.member_count or 0,
                guild2.member_count or 0,
                ping_a,
                ping_b,
                host_guild_id,
            )

        logger.debug(
            "sending ad2 -> #%s in %s (%d)", channel1.name, guild1.name, server1_id
        )
        try:
            await channel1.send(ad2, view=AddBotView(partnership_id))
            logger.debug("sent ad2 -> %d #%s OK", server1_id, channel1.name)
        except Exception as e:
            logger.error("failed sending to %d #%s: %s", server1_id, channel1.name, e)
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM partnerships WHERE id = $1", partnership_id
                )
            return None, None
        logger.debug(
            "sending ad1 -> #%s in %s (%d)", channel2.name, guild2.name, server2_id
        )
        try:
            await channel2.send(ad1, view=AddBotView(partnership_id))
            logger.debug("sent ad1 -> %d #%s OK", server2_id, channel2.name)
        except Exception as e:
            logger.error("failed sending to %d #%s: %s", server2_id, channel2.name, e)
            async with self.db_pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM partnerships WHERE id = $1", partnership_id
                )
            return None, None

        await self.set_cooldown(server1_id, server2_id)
        await self.set_server_last_partner(server1_id)
        await self.set_server_last_partner(server2_id)

        now = time.time()
        async with self.redis.pipeline(transaction=False) as pipe:
            pipe.zadd(
                "stats:partners:24h",
                {
                    f"{min(server1_id, server2_id)}:{max(server1_id, server2_id)}:{now:.0f}": now
                },
            )
            pipe.zremrangebyscore("stats:partners:24h", 0, now - 86400)
            await pipe.execute()
        count = await self.redis.zcard("stats:partners:24h")
        await self.redis.set("stats:partners", count)

        logger.info("partner success: %s <-> %s", guild1.name, guild2.name)
        return channel1, channel2

    async def scan_ad(self, ad: str) -> dict:
        hits = []
        lower = ad.lower()
        for rule, patterns in RULE_PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, lower):
                    hits.append(f"{rule}: {m.group()}")
        regex_hits = list(set(hits))
        if regex_hits:
            return {
                "sus": True,
                "confidence": 0.95,
                "ai_hits": [],
                "regex_hits": regex_hits,
                "user_reason": "Your ad was flagged during the regex prescan",
            }
        try:
            message = await self.client.messages.create(
                model=self.bot.yaml_config["ai"]["model"],
                max_tokens=self.bot.yaml_config["ai"]["max_tokens"],
                temperature=self.bot.yaml_config["ai"]["temperature"],
                system=[
                    {
                        "type": "text",
                        "text": SCAN_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[
                    {"role": "user", "content": f"Advertisement:\n{ad}"},
                    {"role": "assistant", "content": "{"},
                ],
            )
        except APIStatusError as e:
            if e.status_code in (503, 529):
                logger.warning(
                    "Claude API unavailable (%s), skipping scan", e.status_code
                )
                return {
                    "sus": False,
                    "confidence": 0.0,
                    "ai_hits": [],
                    "regex_hits": [],
                    "user_reason": "AI scan unavailable",
                }
            raise
        try:
            raw = "{" + message.content[0].text.strip()
            result = json.loads(raw)
        except (json.JSONDecodeError, IndexError):
            logger.error("failed to parse claude response for ad: %.100s", ad)
            result = {
                "sus": True,
                "confidence": 0.5,
                "ai_hits": [],
                "regex_hits": [],
                "user_reason": "Your ad could not be automatically verified. Please review the server rules and resubmit.",
            }

        if result.get("sus"):
            guild: discord.Guild = self.bot.get_guild(
                self.bot.yaml_config["bot"]["support_guild"]
            )
            channel: discord.TextChannel = (
                guild.get_channel(self.bot.yaml_config["channels"]["flagged_ads"])
                if guild
                else None
            )
            if channel:
                result_str = str(result)
                if len(result_str) > 1000:
                    result_str = result_str[:1000] + "..."
                ad_str = ad if len(ad) <= 1000 else ad[:1000] + "..."
                embed = discord.Embed(title="Ad flagged", color=discord.Color.fuchsia())
                embed.add_field(
                    name="Json", value=f"```\n{result_str}\n```", inline=False
                )
                embed.add_field(name="Ad", value=f"```\n{ad_str}\n```", inline=False)
                try:
                    await channel.send(
                        f"<@&{self.bot.yaml_config['roles']['staff']}> Flagged Ad, Confidence: {result.get('confidence', 0.5)}",
                        embed=embed,
                    )
                except Exception:
                    logger.error(
                        "Failed sending Ad scan result to channel", exc_info=True
                    )
            else:
                logger.error("flagged_ads channel or support_guild not found")
        return result

    async def index_ad(self, guild_id: int, config: dict | None = None) -> bool:
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return False
        if config is None:
            config = await self.bot.config.get(guild_id)
        if not config:
            return False
        log_channel = guild.get_channel(config.get("log_channel"))
        ad_channel = guild.get_channel(config.get("ad_channel"))
        if not ad_channel:
            if log_channel and await self._can_warn(guild_id, "ad_channel"):
                try:
                    await log_channel.send(
                        embed=discord.Embed(
                            title="Ad channel missing",
                            description="Use `/config set` to set one",
                            color=discord.Color.dark_red(),
                        )
                    )
                except discord.HTTPException:
                    pass
            return False
        whitelisted = await self.redis.smembers("whitelisted_links")
        try:
            async for message in ad_channel.history(limit=10):
                if LINK_REGEX.search(message.content):
                    ad_message = message.content
                    for link in whitelisted:
                        ad_message = ad_message.replace(link, "")
                    ad_hash = hashlib.sha256(ad_message.encode()).hexdigest()[:12]
                    ver = self.bot.yaml_config["cache"]["claude_cache_version"]
                    cached = await self.redis.get(f"{ver}:claude:{ad_hash}")
                    if not cached:
                        async with self._scan_semaphore:
                            try:
                                scan_result = await asyncio.wait_for(
                                    self.scan_ad(ad_message),
                                    timeout=self.bot.yaml_config["delays"][
                                        "scan_timeout"
                                    ],
                                )
                            except asyncio.TimeoutError:
                                scan_result = {
                                    "sus": False,
                                    "confidence": 0.5,
                                    "ai_hits": [],
                                    "regex_hits": [],
                                    "user_reason": "Timed out",
                                }
                            cached = json.dumps(scan_result, indent=2)
                            await self.redis.set(
                                f"{ver}:claude:{ad_hash}",
                                cached,
                                ex=self.bot.yaml_config["cache"]["scan_result_ttl"],
                            )
                            await asyncio.sleep(
                                self.bot.yaml_config["delays"]["scan_ad"]
                            )
                    await self.redis.set(f"ads:{guild_id}", PING_RE.sub("", ad_message))
                    return True
        except discord.HTTPException as e:
            logger.warning("HTTP error fetching history for %d: %s", guild_id, e)
            return False
        if log_channel and await self._can_warn(guild_id, "ad_missing"):
            try:
                await log_channel.send(
                    embed=discord.Embed(
                        title="Ad message missing",
                        description="Your ad message was not found in the recent 10 messages in the channel",
                        color=discord.Color.dark_red(),
                    )
                )
            except discord.HTTPException:
                pass
        return False

    async def index_ads(self) -> dict:
        whitelisted = await self.redis.smembers("whitelisted_links")
        missing_channel_embed = discord.Embed(
            title="Ad channel missing",
            description="Use `/config set` to set one",
            color=discord.Color.dark_red(),
        )
        missing_ad_embed = discord.Embed(
            title="Ad message missing",
            description="Your ad message was not found in the recent 10 messages in the channel",
            color=discord.Color.dark_red(),
        )
        pending = []
        summary = {
            "total": len(self.bot.guilds),
            "no_config": 0,
            "missing_channel": 0,
            "cached": 0,
            "missing_ad": 0,
        }
        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            if not config:
                summary["no_config"] += 1
                continue
            ad_channel = guild.get_channel(config.get("ad_channel"))
            log_channel = guild.get_channel(config.get("log_channel"))
            if not ad_channel:
                summary["missing_channel"] += 1
                if log_channel:
                    try:
                        await log_channel.send(embed=missing_channel_embed)
                    except discord.HTTPException:
                        pass
                continue
            ad_message = None
            try:
                async for message in ad_channel.history(limit=10):
                    if LINK_REGEX.search(message.content):
                        ad_message = message.content
                        for link in whitelisted:
                            ad_message = ad_message.replace(link, "")
                        ad_hash = hashlib.sha256(ad_message.encode()).hexdigest()[:12]
                        ver = self.bot.yaml_config["cache"]["claude_cache_version"]
                        cached = await self.redis.get(f"{ver}:claude:{ad_hash}")
                        if not cached:
                            async with self._scan_semaphore:
                                try:
                                    scan_result = await asyncio.wait_for(
                                        self.scan_ad(ad_message),
                                        timeout=self.bot.yaml_config["delays"][
                                            "scan_timeout"
                                        ],
                                    )
                                except asyncio.TimeoutError:
                                    scan_result = {
                                        "sus": False,
                                        "confidence": 0.5,
                                        "ai_hits": [],
                                        "regex_hits": [],
                                        "user_reason": "Timed out",
                                    }
                                cached = json.dumps(scan_result, indent=2)
                                await self.redis.set(
                                    f"{ver}:claude:{ad_hash}",
                                    cached,
                                    ex=self.bot.yaml_config["cache"]["scan_result_ttl"],
                                )
                                await asyncio.sleep(
                                    self.bot.yaml_config["delays"]["scan_ad"]
                                )
                        break
            except discord.HTTPException as e:
                logger.warning("HTTP error fetching history for %s: %s", guild.name, e)
                continue
            if ad_message:
                pending.append((f"ads:{guild.id}", PING_RE.sub("", ad_message)))
                summary["cached"] += 1
            else:
                summary["missing_ad"] += 1
                if log_channel:
                    try:
                        await log_channel.send(embed=missing_ad_embed)
                    except discord.HTTPException:
                        pass
            await asyncio.sleep(0)
        batch = self.bot.yaml_config["cache"]["pipeline_batch"]
        for i in range(0, max(len(pending), 1), batch):
            chunk = pending[i : i + batch]
            if not chunk:
                break
            async with self.redis.pipeline() as pipe:
                for key, value in chunk:
                    pipe.set(key, value)
                await pipe.execute()
            await asyncio.sleep(0)
        return summary

    async def cog_load(self):
        self.bot.add_view(AddBotView())
        self.bot.add_dynamic_items(
            PartnerInfoButton, ReportButton, ReportBlacklistButton, ReportDismissButton
        )
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT link FROM whitelisted_links")
        await self.redis.delete("whitelisted_links")
        if rows:
            await self.redis.sadd("whitelisted_links", *[r["link"] for r in rows])
        if self.bot.is_ready() and not self.partner_loop.is_running():
            logger.debug("bot already ready, starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("bot not ready yet, loop will start on_ready")

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(AddBotView())
        if not self.partner_loop.is_running():
            logger.info("starting partner_loop")
            self.partner_loop.start()
        else:
            logger.debug("partner_loop already running")

    async def _run_partner_round(self):
        async with self.db_pool.acquire() as conn:
            rows = await conn.fetch("SELECT guild_id FROM blacklists")
            blacklisted_ids = {row[0] for row in rows}

        now = time.time()
        available = []
        for guild in self.bot.guilds:
            if guild.id in blacklisted_ids:
                continue
            config = await self.bot.config.get(guild.id)
            if not config:
                continue

            partner_delay = (
                config.get("partner_delay")
                or self.bot.yaml_config["partner_delay"]["default"]
            )
            last = await self.get_server_last_partner(guild.id)
            if last is not None and (now - last) < partner_delay:
                logger.debug(
                    "skip %s (%d): cooldown %.0fs remaining",
                    guild.name,
                    guild.id,
                    partner_delay - (now - last),
                )
                continue

            partner_channel = guild.get_channel(config.get("partner_channel"))
            member_role = guild.get_role(config.get("member_role"))
            partner_ping_role = guild.get_role(config.get("partner_ping_role"))

            missing = []
            if not partner_channel:
                missing.append("partner_channel")
            if not config.get("ad_channel"):
                missing.append("ad_channel")
            if not member_role:
                missing.append("member_role")
            if not partner_ping_role:
                missing.append("partner_ping_role")
            if missing:
                logger.debug(
                    "skip %s (%d): missing config — %s",
                    guild.name,
                    guild.id,
                    ", ".join(missing),
                )
                continue

            if not isinstance(partner_channel, discord.TextChannel):
                logger.debug(
                    "skip %s (%d): partner_channel is wrong type", guild.name, guild.id
                )
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel and await self._can_warn(guild.id, "wrong_channel_type"):
                    try:
                        await log_channel.send(
                            embed=discord.Embed(
                                title="Partner channel not found",
                                description="Use `/config set` to set one",
                                color=discord.Color.dark_red(),
                            )
                        )
                    except discord.HTTPException:
                        pass
                continue

            perms = partner_channel.permissions_for(guild.me)
            if not perms.send_messages or not perms.mention_everyone:
                logger.debug(
                    "skip %s (%d): missing perms in #%s — send=%s mention=%s",
                    guild.name,
                    guild.id,
                    partner_channel.name,
                    perms.send_messages,
                    perms.mention_everyone,
                )
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel and await self._can_warn(guild.id, "missing_perms"):
                    try:
                        await log_channel.send(
                            embed=discord.Embed(
                                title="Missing permissions",
                                description="I need `Send Messages` and `Mention Everyone` permissions in the partner channel",
                                color=discord.Color.dark_red(),
                            )
                        )
                    except discord.HTTPException:
                        pass
                continue

            reason = await self.validate_server(guild, config)
            if reason:
                logger.debug(
                    "skip %s (%d): validation failed — %s", guild.name, guild.id, reason
                )
                log_channel = guild.get_channel(config.get("log_channel"))
                if log_channel and await self._can_warn(guild.id, "validation"):
                    try:
                        await log_channel.send(
                            embed=discord.Embed(
                                title="Requirements not met",
                                description=reason,
                                color=discord.Color.dark_red(),
                            )
                        )
                    except discord.HTTPException:
                        pass
                continue

            if guild.member_count is None:
                logger.debug("skip %s (%d): member_count is None", guild.name, guild.id)
                continue

            indexed = await self.index_ad(guild.id, config=config)
            if not indexed:
                logger.debug("skip %s (%d): no ad indexed", guild.name, guild.id)
                continue

            logger.debug(
                "eligible %s (%d) members=%d", guild.name, guild.id, guild.member_count
            )
            available.append((guild.id, guild.member_count))
            await asyncio.sleep(0)

        pairs, sat_out = await self.match_servers(available)

        for a, b in pairs:
            guild_a: discord.Guild = self.bot.get_guild(a)
            guild_b: discord.Guild = self.bot.get_guild(b)
            logger.debug(
                "attempting pair: %s <-> %s",
                guild_a.name if guild_a else a,
                guild_b.name if guild_b else b,
            )
            ch1, ch2 = await self.partner(a, b)
            await asyncio.sleep(self.bot.yaml_config["delays"]["partner_pair"])
            if ch1 and ch2:
                logger.debug(
                    "success: %s <-> %s",
                    guild_a.name if guild_a else a,
                    guild_b.name if guild_b else b,
                )
            else:
                logger.warning(
                    "failed pair: %s <-> %s — see reason above",
                    guild_a.name if guild_a else a,
                    guild_b.name if guild_b else b,
                )
        if pairs:
            logger.info(
                "Finished round with %d eligible, %d pairs, %d sat out",
                len(available),
                len(pairs),
                len(sat_out),
            )
        else:
            logger.debug(
                "Finished round with %d eligible, %d pairs, %d sat out",
                len(available),
                len(pairs),
                len(sat_out),
            )

    @tasks.loop(seconds=60)
    async def partner_loop(self):
        logger.debug("loop #%d fired", self.partner_loop.current_loop)
        if self._partner_lock.locked():
            logger.debug("skipping — already running in this process")
            return
        async with self._partner_lock:
            acquired = await self.redis.set(
                "last_partner_run",
                1,
                nx=True,
                ex=self.bot.yaml_config["cache"]["redis_lock"],
            )
            if not acquired:
                logger.debug(
                    "skipping — another instance already running (last_partner_run key exists)"
                )
                return
            logger.debug("[loop] acquired lock, proceeding")
            await self._run_partner_round()

    @partner_loop.before_loop
    async def before_partner_loop(self):
        await self.bot.wait_until_ready()

    @partnerGroup.command(
        name="reqs", description="Show partner reqs depending on membercount"
    )
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    async def partner_reqs(
        self, interaction: discord.Interaction, membercount: int = 1000
    ):
        config_req = self.bot.yaml_config["partner_requirements"]
        scale = membercount / config_req["scale"]
        c1 = round(config_req["below_do_none"] * scale)
        c2 = round(config_req["below_do_partner"] * scale)
        c3 = round(config_req["below_do_here"] * scale)
        c4 = round(config_req["below_do_partnerhere"] * scale)

        lines = [
            f"- **1 - {c1}** - none",
            f"- **{c1 + 1} - {c2}** - partner",
            f"- **{c2 + 1} - {c3}** - here",
            f"- **{c3 + 1} - {c4}** - here + partner",
            f"- **{c4 + 1} - {membercount}** - member",
        ]

        embed = discord.Embed(
            title="Partner Reqs",
            description="\n".join(lines),
            color=discord.Color.fuchsia(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @partnerGroup.command(name="force")
    @is_owner()
    async def force_partner(
        self, interaction: discord.Interaction, server_id_1: str, server_id_2: str
    ):
        logger.info(
            "[force_partner] invoked by %d: %s <-> %s",
            interaction.user.id,
            server_id_1,
            server_id_2,
        )
        await interaction.response.defer(ephemeral=True)
        if server_id_1 == server_id_2:
            logger.warning("[force_partner] rejected: same server id %s", server_id_1)
            await interaction.followup.send(
                "Cannot partner a server with itself.", ephemeral=True
            )
            return
        try:
            channel1, channel2 = await self.partner(int(server_id_1), int(server_id_2))
        except Exception as e:
            logger.error("[force_partner] exception: %s", e, exc_info=True)
            await interaction.followup.send(f"Error: {e}", ephemeral=True)
            return
        if not channel1:
            logger.warning(
                "[force_partner] partner() returned None for %s <-> %s",
                server_id_1,
                server_id_2,
            )
            await interaction.followup.send(
                "Failed - check logs and console for details.", ephemeral=True
            )
            return
        logger.info("[force_partner] SUCCESS: %s <-> %s", channel1, channel2)
        await interaction.followup.send(
            f"Partnered: {channel1.mention} | {channel2.mention}", ephemeral=True
        )

    @partnerGroup.command(name="ad", description="Send a server's partner ad")
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    async def send_ad(self, interaction: discord.Interaction, guild_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.followup.send("Invalid guild id", ephemeral=True)
            return
        ad = await self.redis.get(f"ads:{gid}")
        if not ad:
            await self.index_ad(gid)
            ad = await self.redis.get(f"ads:{gid}")
        if not ad:
            await interaction.followup.send(
                "No ad found for that server.", ephemeral=True
            )
            return
        await interaction.followup.send(ad, ephemeral=True)

    @partnerGroup.command(
        name="status", description="Check why your server may not be getting partnered"
    )
    @is_management()
    @discord.app_commands.checks.cooldown(rate=1, per=10)
    async def partner_status(self, interaction: discord.Interaction):
        guild = interaction.guild

        async with self.db_pool.acquire() as conn:
            bl = await conn.fetchrow(
                "SELECT reason FROM blacklists WHERE guild_id = $1", guild.id
            )
        if bl:
            await interaction.response.send_message(
                f"Your server is **blacklisted**: {bl['reason']}", ephemeral=True
            )
            return

        config = await self.bot.config.get(guild.id)
        if not config:
            await interaction.response.send_message(
                "No configuration found. Run `/setup` to get started.", ephemeral=True
            )
            return

        partner_channel = guild.get_channel(config.get("partner_channel"))
        ad_channel = guild.get_channel(config.get("ad_channel"))
        member_role = guild.get_role(config.get("member_role"))
        partner_ping_role = guild.get_role(config.get("partner_ping_role"))

        missing = []
        if not partner_channel:
            missing.append("partner channel")
        if not ad_channel:
            missing.append("ad channel")
        if not member_role:
            missing.append("member role")
        if not partner_ping_role:
            missing.append("partner ping role")
        if missing:
            await interaction.response.send_message(
                f"Missing config: {', '.join(missing)}. Use `/config set` to fix.",
                ephemeral=True,
            )
            return

        if not isinstance(partner_channel, discord.TextChannel):
            await interaction.response.send_message(
                "Partner channel must be a text channel.", ephemeral=True
            )
            return

        perms = partner_channel.permissions_for(guild.me)
        if not perms.send_messages or not perms.mention_everyone:
            await interaction.response.send_message(
                f"Missing permissions in {partner_channel.mention}: need **Send Messages** and **Mention Everyone**.",
                ephemeral=True,
            )
            return

        ad = await self.redis.get(f"ads:{guild.id}")
        if not ad:
            await interaction.response.send_message(
                "No ad found. Make sure your ad channel has a message with a link, then run `/config set` to re-index.",
                ephemeral=True,
            )
            return

        reason = await self.validate_server(guild, config)
        if reason:
            await interaction.response.send_message(reason, ephemeral=True)
            return

        await interaction.response.send_message(
            "Your server is eligible for partnering.", ephemeral=True
        )

    @partnerGroup.command(
        name="indexads", description="Re-index all server ads and show a summary"
    )
    @is_owner()
    async def indexads(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        summary = await self.index_ads()
        embed = discord.Embed(title="Ad Index Summary", color=discord.Color.fuchsia())
        embed.add_field(name="Total Guilds", value=str(summary["total"]), inline=True)
        embed.add_field(name="Cached", value=str(summary["cached"]), inline=True)
        embed.add_field(
            name="Missing Ad", value=str(summary["missing_ad"]), inline=True
        )
        embed.add_field(
            name="Missing Channel", value=str(summary["missing_channel"]), inline=True
        )
        embed.add_field(name="No Config", value=str(summary["no_config"]), inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @partnerGroup.command(name="loopforce")
    @is_owner()
    async def forceloop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if self._partner_lock.locked():
            await interaction.followup.send(
                "Already running, wait for it to finish.", ephemeral=True
            )
            return
        async with self._partner_lock:
            logger.info("[forceloop] force-acquired lock, proceeding")
            await self.redis.set(
                "last_partner_run", 1, ex=self.bot.yaml_config["cache"]["redis_lock"]
            )
            await self._run_partner_round()
        await interaction.followup.send("Partner loop complete", ephemeral=True)

    @partnerGroup.command(
        name="broadcast", description="Send a server's ad to every partner channel"
    )
    @is_owner()
    @discord.app_commands.checks.cooldown(rate=1, per=86400)
    async def broadcast_ad(self, interaction: discord.Interaction, guild_id: str):
        await interaction.response.defer(ephemeral=True)
        try:
            gid = int(guild_id)
        except ValueError:
            await interaction.followup.send("Invalid guild id.", ephemeral=True)
            return

        ad = await self.redis.get(f"ads:{gid}")
        if not ad:
            await interaction.followup.send(
                "No ad found for that server.", ephemeral=True
            )
            return

        sent, failed = 0, 0
        for guild in self.bot.guilds:
            if guild.id == gid:
                continue
            config = await self.bot.config.get(guild.id)
            if not config:
                continue
            channel = guild.get_channel(config.get("partner_channel"))
            if not isinstance(channel, discord.TextChannel):
                continue
            try:
                await channel.send(ad, view=AddBotView())
                sent += 1
                await asyncio.sleep(self.bot.yaml_config["delays"]["partner_pair"])
            except discord.HTTPException:
                failed += 1

        await interaction.followup.send(
            f"Broadcast complete: {sent} sent, {failed} failed.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Partner(bot))
