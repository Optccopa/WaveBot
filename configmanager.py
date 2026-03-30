import json

class ConfigManager:
    def __init__(self, db_pool, redis):
        self.db = db_pool
        self.redis = redis

    async def get(self, guild_id: int):
        key = f"config:{guild_id}"

        # 1. Try Redis
        cached = await self.redis.get(key)
        if cached:
            return json.loads(cached)

        # 2. Fallback to Postgres
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM guild_config WHERE guild_id = $1",
                guild_id
            )

        if not row:
            return None

        data = dict(row)

        # 3. Store in Redis
        await self.redis.set(key, json.dumps(data))

        return data

    async def set(self, guild_id: int, **fields):
        # Build dynamic query
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

        # Update Redis
        key = f"config:{guild_id}"
        config = await self.get(guild_id) or {}
        config.update(fields)

        await self.redis.set(key, json.dumps(config))

    async def invalidate(self, guild_id: int):
        await self.redis.delete(f"config:{guild_id}")