import json

from redis.asyncio import Redis

ALLOWED_COLUMNS = {"partner_channel", "ad_channel", "member_role", "partner_ping_role", "log_channel", "partner_delay"}

class ConfigManager:
    def __init__(self, db_pool, redis):
        self.db = db_pool
        self.redis: Redis = redis

    async def get(self, guild_id: int):
        key = f"config:{guild_id}"

        cached = await self.redis.get(key)
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, ValueError):
                await self.redis.delete(key)

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )

        if not row:
            return None

        data = dict(row)

        await self.redis.set(key, json.dumps(data), ex=2592000)

        return data

    async def set(self, guild_id: int, **fields):
        invalid = set(fields) - ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid config fields: {invalid}")

        columns = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        values = list(fields.values())
        async with self.db.acquire() as conn:
            await conn.execute(
                f"""
                INSERT INTO guild_config (guild_id, {", ".join(fields)})
                VALUES ($1, {", ".join(f"${i+2}" for i in range(len(fields)))})
                ON CONFLICT (guild_id)
                DO UPDATE SET {columns}
                """,
                guild_id,
                *values
            )

        # Invalidate then re-read from DB — avoids read-merge-write race
        await self.redis.delete(f"config:{guild_id}")
        await self.get(guild_id)

    async def get_all(self) -> dict[int, dict]:
        async with self.db.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM guild_config")
        if not rows:
            return {}
        configs = {}
        async with self.redis.pipeline(transaction=False) as pipe:
            for row in rows:
                data = dict(row)
                guild_id = data["guild_id"]
                configs[guild_id] = data
                pipe.set(f"config:{guild_id}", json.dumps(data), ex=2592000)
            await pipe.execute()
        return configs

    async def invalidate(self, guild_id: int):
        await self.redis.delete(f"config:{guild_id}")
