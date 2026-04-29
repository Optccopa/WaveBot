import discord, os, asyncio, asyncpg, sys, logging, aiohttp, yaml, json
from aiohttp import web
from redis.asyncio import Redis
from discord.ext import commands
from src.configmanager import ConfigManager
from src.utils import retry_with_backoff

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

class WebhookHandler(logging.Handler):
    def __init__(self, url: str, loop: asyncio.AbstractEventLoop):
        super().__init__(level=logging.INFO)
        self.url = url
        self.loop = loop
        self.session = aiohttp.ClientSession()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=500)
        self._task = loop.create_task(self._worker())

    def _enqueue(self, msg: str):
        try:
            self._queue.put_nowait(msg)
        except asyncio.QueueFull:
            pass

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        try:
            self.loop.call_soon_threadsafe(self._enqueue, msg)
        except RuntimeError:
            pass

    async def _worker(self):

        while True:
            msg = await self._queue.get()
            await asyncio.sleep(2)
            batch = [msg]
            while not self._queue.empty():
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            embeds = []
            fields, chars = [], 0
            for entry in batch:
                value = f"```\n{entry[:1014]}\n```"
                if fields and (len(fields) >= 25 or chars + len(value) > 5800):
                    embeds.append({"color": 0xEB459E, "fields": fields})
                    fields, chars = [], 0
                fields.append({"name": "\u200b", "value": value, "inline": False})
                chars += len(value)
            if fields:
                embeds.append({"color": 0xEB459E, "fields": fields})

            try:
                for i in range(0, len(embeds), 10):
                    payload = {"embeds": embeds[i:i + 10]}
                    for attempt in range(3):
                        try:
                            resp = await self.session.post(self.url, json=payload)
                            if resp.status == 429:
                                data = await resp.json()
                                wait = data.get("retry_after", 1)
                                print(f"[WebhookHandler] 429 rate limited, retry_after={wait}s (attempt {attempt+1}/3)", file=sys.stderr)
                                await asyncio.sleep(wait)
                                continue
                            if resp.status >= 400:
                                print(f"[WebhookHandler] HTTP {resp.status} on attempt {attempt+1}/3, retrying", file=sys.stderr)
                                await asyncio.sleep(1)
                                continue
                            break
                        except Exception as e:
                            print(f"[WebhookHandler] Exception on attempt {attempt+1}/3: {e}", file=sys.stderr)
                            await asyncio.sleep(1)
                    else:
                        print(f"[WebhookHandler] Failed to deliver embed group after 3 attempts, dropping {len(embeds[i:i+10])} embeds", file=sys.stderr)
            finally:
                for _ in batch:
                    self._queue.task_done()

    async def close_async(self):
        await self._queue.join()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        await self.session.close()

class Bot(commands.AutoShardedBot):
    def __init__(self):

        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True

        super().__init__(
            command_prefix="p!",
            intents=intents,
            chunk_guilds_at_startup=True
        )

        self.db_pool = None
        self.redis = None

        with open("config.yaml", "r") as f:
            self.yaml_config = yaml.safe_load(f)

    async def setup_hook(self):
        url = os.getenv("LOG_WEBHOOK_URL")
        if url:
            logging.getLogger().addHandler(WebhookHandler(url, asyncio.get_running_loop()))

        self.redis: Redis = Redis(
            host="redis",
            port=6379,
            decode_responses=True
        )

        self.db_pool: asyncpg.Pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            user=os.getenv("POSTGRES_USER", "appuser"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB", "appdb")
        )
        
        # create tables
        async with self.db_pool.acquire() as conn:
            conn: asyncpg.Connection
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    partner_channel BIGINT,
                    ad_channel BIGINT,
                    member_role BIGINT,
                    partner_ping_role BIGINT,
                    log_channel BIGINT,
                    partner_delay INTEGER DEFAULT 21600,
                    premium BOOLEAN DEFAULT FALSE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS blacklists (
                    guild_id BIGINT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    added_by BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS whitelisted_links (
                    link TEXT PRIMARY KEY,
                    added_by BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS early_access (
                    guild_id BIGINT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    reason TEXT
                )
            """)

        # load cogs
        if os.path.isdir("cogs"):
            for file in os.listdir("cogs"):
                if file.endswith(".py") and not file.startswith("_"):
                    ext = f"cogs.{file[:-3]}"
                    try:
                        await self.load_extension(ext)
                    except Exception as e:
                        log.error("Failed to load %s: %s", ext, e)

        # init config manager
        self.config = ConfigManager(self.db_pool, self.redis)


        await retry_with_backoff(self.tree.sync)

    async def start_with_retries(self):
        for i in range(3):
            try:
                await self.start(os.getenv("DISCORD_TOKEN")) 
                return

            except discord.LoginFailure:
                log.error("Invalid token")
                return

            except (discord.GatewayNotFound, OSError) as e:
                log.error("Gateway error (%d retries left): %s", 2 - i, e)
                await asyncio.sleep(30)

        log.error("Failed starting on all trys")
        sys.exit(1)

    async def on_ready(self):
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.delete("bot:guild_ids")
            if self.guilds:
                pipe.sadd("bot:guild_ids", *[g.id for g in self.guilds])
            await pipe.execute()
            await self.redis.hset("bot:guild_info", mapping={
                str(g.id): json.dumps({
                    "name": g.name,
                    "icon": str(g.icon) if g.icon else None,
                    "member_count": g.member_count,
                })
                for g in self.guilds
            })
        log.info("[on_ready] seeded %d guilds into bot:guild_ids", len(self.guilds))
        async with self.db_pool.acquire() as conn:
            ea_rows = await conn.fetch("SELECT guild_id FROM early_access")
        await self.redis.delete("bot:early_access_guilds")
        if ea_rows:
            await self.redis.sadd("bot:early_access_guilds", *[r["guild_id"] for r in ea_rows])

    async def on_shard_ready(self, shard_id: int):
        await self.change_presence(
            activity=discord.CustomActivity(name=f"Shard {shard_id + 1}/{self.shard_count}")
        )
        log.info("Shard %d ready", shard_id)

    async def close(self):
        if self.db_pool: await self.db_pool.close()
        if self.redis: await self.redis.aclose()
        for handler in logging.getLogger().handlers:
            if isinstance(handler, WebhookHandler):
                await handler.close_async()
        await super().close()

    async def on_guild_remove(self, guild: discord.Guild):
        await self.redis.srem("bot:guild_ids", guild.id)
        await self.redis.hdel("bot:guild_info", guild.id)

    async def on_guild_join(self, guild: discord.Guild):
        if (guild.member_count or 0) < self.yaml_config['requirements']['minimum_membercount']:
            has_access = await self.redis.sismember("bot:early_access_guilds", guild.id)
            if not has_access:
                if guild.owner:
                    try:
                        await guild.owner.send(
                            f"**{self.user.name}** has left **{guild.name}** as it is under the minimum membercount `{self.yaml_config['requirements']['minimum_membercount']}`\n"
                            f"Access: You can request access in {self.yaml_config['bot']['support_invite']} , https://discord.com/channels/1491681410111635478/1491709242829307965"
                        )
                    except discord.Forbidden:
                        pass
                await guild.leave()
                return

        await self.redis.sadd("bot:guild_ids", guild.id)
        await self.redis.hset("bot:guild_info", guild.id, json.dumps({
            "name": guild.name,
            "icon": str(guild.icon) if guild.icon else None,
            "member_count": guild.member_count,
        }))

        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT reason FROM blacklists WHERE guild_id = $1", guild.id)
        if row:
            if guild.owner:
                try:
                    await guild.owner.send(
                        f"**{self.user.name}** has left **{guild.name}** as it is blacklisted.\n"
                        f"Reason: {row['reason']}\n"
                        f"Appeal: You can appeal this in https://discord.gg/uacMXzbAfg, https://discord.com/channels/1491681410111635478/1491709242829307965"
                    )
                except discord.Forbidden:
                    pass
            await guild.leave() 
            return
        
        log.info(f"Joined a new server: {guild.name} with {guild.member_count} members")

bot = Bot()

@bot.command(name="dr")
@commands.cooldown(1,10)
async def pinger(ctx):
    await ctx.reply("Donut")

async def handle_validate(request: web.Request) -> web.Response:
    try:
        guild_id = int(request.match_info["guild_id"])
    except ValueError:
        return web.json_response({"reason": None})
    config = (await request.json()).get("config", {})
    guild = bot.get_guild(guild_id)
    if not guild:
        return web.json_response({"reason": None})
    partner_cog = bot.cogs.get("Partner")
    if not partner_cog:
        return web.json_response({"reason": None})
    reason = await partner_cog.validate_server(guild, config)
    return web.json_response({"reason": reason})

async def main():
    internal_app = web.Application()
    internal_app.router.add_post("/validate/{guild_id}", handle_validate)
    runner = web.AppRunner(internal_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(os.getenv("BOT_INTERNAL_PORT", 8081))).start()
    log.info("Internal validation server listening on :8081")
    async with bot:
        await bot.start_with_retries()
    await runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())