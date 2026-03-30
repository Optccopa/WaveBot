import discord, os, asyncio, asyncpg
from redis.asyncio import Redis
from discord.ext import commands
from dotenv import load_dotenv
from configmanager import ConfigManager
from utils import *

load_dotenv()


class Bot(commands.AutoShardedBot):
    def __init__(self):

        super().__init__(
            command_prefix="!",
            intents=discord.Intents(
                guilds=True,
                messages=True,
                message_content=True,
                members=True
            )
        )

        self.db_pool = None
        self.redis = None

    async def setup_hook(self):
        self.redis = Redis(
            host="redis",
            port=6379,
            decode_responses=True
        )

        self.db_pool = await asyncpg.create_pool(
            host=os.getenv("POSTGRES_HOST", "postgres"),
            user=os.getenv("POSTGRES_USER", "appuser"),
            password=os.getenv("POSTGRES_PASSWORD"),
            database=os.getenv("POSTGRES_DB", "appdb")
        )

        # load cogs
        if os.path.isdir("cogs"):
            for file in os.listdir("cogs"):
                if file.endswith(".py") and not file.startswith("_"):
                    ext = f"cogs.{file[:-3]}"
                    try:
                        await self.load_extension(ext)
                    except Exception as e:
                        print(f"Failed to load {ext}: {e}")
        # create table
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
                );
            """)
            await conn.execute("""
                ALTER TABLE guild_config
                ADD COLUMN IF NOT EXISTS log_channel BIGINT;
                """)

        # init config manager
        self.config = ConfigManager(self.db_pool, self.redis)

    async def start_with_retries(self):
        retries = 3

        while retries > 0:
            try:
                await self.start(os.getenv("DISCORD_TOKEN"))
                break

            except discord.LoginFailure:
                print("Invalid token")
                break

            except (discord.GatewayNotFound, OSError) as e:
                retries -= 1
                print(f"Gateway error ({retries} retries left): {e}")
                await asyncio.sleep(5)

    async def on_ready(self):
        synced = await retry_with_backoff(self.tree.sync)
        print(
            f"- User: {self.user}\n"
            f"- Shards: {self.shard_count}\n"
            f"- Latency: {round(self.latency * 1000)} ms\n"
            f"- Synced {len(synced)} commands"
        )

    async def on_shard_ready(self, shard_id: int):
        print(f"Shard {shard_id} ready")


bot = Bot()


async def main():
    async with bot:
        await bot.start_with_retries()


if __name__ == "__main__":
    asyncio.run(main())