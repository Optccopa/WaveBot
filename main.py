import discord, os, asyncio, asyncpg, inspect, sys
from redis.asyncio import Redis
from discord.ext import commands
from discord import app_commands
from src.configmanager import ConfigManager
from src.utils import retry_with_backoff
from src import groups


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
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS blacklists (
                    guild_id BIGINT PRIMARY KEY,
                    reason TEXT NOT NULL,
                    added_by BIGINT NOT NULL
                )
            """)

        # init config manager
        self.config = ConfigManager(self.db_pool, self.redis)
        
        for _, obj in inspect.getmembers(groups):
            if isinstance(obj, app_commands.Group):
                self.tree.add_command(obj)

        await retry_with_backoff(self.tree.sync)

    async def start_with_retries(self):
        for i in range(3):
            try:
                await self.start(os.getenv("DISCORD_TOKEN"))
                return

            except discord.LoginFailure:
                print("Invalid token")
                return

            except (discord.GatewayNotFound, OSError) as e:
                print(f"Gateway error ({2 - i} retries left): {e}")
                await asyncio.sleep(30)

        sys.exit(1)

    async def on_ready(self):
        print(
            f"- User: {self.user}\n"
            f"- Shards: {self.shard_count}"
        )

    async def on_shard_ready(self, shard_id: int):
        await self.change_presence(
            activity=discord.CustomActivity(name=f"Shard {shard_id + 1}/{self.shard_count}")
        )
        print(f"Shard {shard_id} ready")

    async def close(self):
        if self.db_pool: await self.db_pool.close()
        if self.redis: await self.redis.aclose()
        await super().close()

    async def on_guild_join(self, guild: discord.Guild):
        async with self.db_pool.acquire() as conn:
            row = await conn.fetchrow("SELECT reason FROM blacklists WHERE guild_id = $1", guild.id)
        if row:
            try:
                await guild.owner.send(
                    f"**{self.bot.user.name}** has left **{guild.name}** as it is blacklisted.\n"
                    f"Reason: {row['reason']}"
                )
            except discord.Forbidden:
                pass
            finally:
                await guild.leave()

bot = Bot()

async def main():
    async with bot:
        await bot.start_with_retries()

if __name__ == "__main__":
    asyncio.run(main())