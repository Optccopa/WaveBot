import json
from redis.asyncio import Redis

ALLOWED_COLUMNS = {"available_pings"}

class PremiumManager:
    def __init__(self, db_pool, redis):
        self.db = db_pool
        self.redis: Redis = redis

    async def get(self, guild_id: int) -> dict | None:
        key = f"premium:{guild_id}"
        cached = await self.redis.get(key)
        if cached:
            try:
                return json.loads(cached)
            except (json.JSONDecodeError, ValueError):
                await self.redis.delete(key)
        async with self.db.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM premium WHERE guild_id = $1", guild_id)
        if not row:
            return None
        data = dict(row)
        data["added_at"] = data["added_at"].isoformat() if data.get("added_at") else None
        await self.redis.set(key, json.dumps(data), ex=2592000)
        return data

    async def set(self, guild_id: int, **fields):
        invalid = set(fields) - ALLOWED_COLUMNS
        if invalid:
            raise ValueError(f"Invalid premium fields: {invalid}")
        columns = ", ".join(f"{k} = ${i+2}" for i, k in enumerate(fields))
        async with self.db.acquire() as conn:
            await conn.execute(
                f"UPDATE premium SET {columns} WHERE guild_id = $1",
                guild_id, *fields.values()
            )
        await self.redis.delete(f"premium:{guild_id}")
        await self.get(guild_id)

    async def add(self, guild_id: int, added_by: int):
        async with self.db.acquire() as conn:
            await conn.execute(
                "INSERT INTO premium (guild_id, added_by) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                guild_id, added_by
            )
        await self.redis.delete(f"premium:{guild_id}")
        await self.get(guild_id)

    async def remove(self, guild_id: int):
        async with self.db.acquire() as conn:
            await conn.execute("DELETE FROM premium WHERE guild_id = $1", guild_id)
        await self.redis.delete(f"premium:{guild_id}")
