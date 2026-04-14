import discord, os, asyncio, asyncpg, sys, logging, aiohttp
from redis.asyncio import Redis
from discord.ext import commands
from src.configmanager import ConfigManager
from src.utils import retry_with_backoff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logging.getLogger("discord").setLevel(logging.WARNING)
logging.getLogger("discord.http").setLevel(logging.WARNING)

log = logging.getLogger(__name__)

class WebhookHandler(logging.Handler):
    def __init__(self, url: str):
        super().__init__(level=logging.INFO)
        self.url = url

    def emit(self, record: logging.LogRecord):
        msg = self.format(record)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._send(msg))
        except RuntimeError:
            pass

    async def _send(self, msg: str):
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(self.url, json={"content": f"```\n{msg[:1990]}\n```"})
        except Exception:
            pass

class Bot(commands.AutoShardedBot):
    def __init__(self):

        super().__init__(
            command_prefix="p!",
            intents=discord.Intents.all(),
            chunk_guilds_at_startup=True
        )

        self.db_pool = None
        self.redis = None

    async def setup_hook(self):
        url = os.getenv("LOG_WEBHOOK_URL")
        if url:
            logging.getLogger().addHandler(WebhookHandler(url))

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
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id BIGINT PRIMARY KEY,
                    partner_channel BIGINT,
                    ad_channel BIGINT,
                    member_role BIGINT,
                    partner_ping_role BIGINT,
                    log_channel BIGINT,
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

    async def on_shard_ready(self, shard_id: int):
        await self.change_presence(
            activity=discord.CustomActivity(name=f"Shard {shard_id + 1}/{self.shard_count}")
        )
        log.info("Shard %d ready", shard_id)

    async def close(self):
        if self.db_pool: await self.db_pool.close()
        if self.redis: await self.redis.aclose()
        await super().close()

    async def on_guild_join(self, guild: discord.Guild):
        if guild.member_count < 50:
            if guild.owner:
                try:
                    await guild.owner.send(
                        f"**{self.user.name}** has left **{guild.name}** as it is under the minimum membercount `50`\n"
                        f"Access: You can request access in https://discord.gg/uacMXzbAfg , https://discord.com/channels/1491681410111635478/1491709242829307965"
                    )
                except discord.Forbidden:
                    pass
            await guild.leave()

            return

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

bot = Bot()

@bot.command(name="dr")
async def pinger(ctx):
    await ctx.reply("Donut")

async def main():
    async with bot:
        await bot.start_with_retries()

if __name__ == "__main__":
    asyncio.run(main())