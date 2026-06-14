# Database Reference

## Schema (schema.sql)

```sql
guild_config (
    guild_id          BIGINT PRIMARY KEY,
    partner_channel   BIGINT,
    ad_channel        BIGINT,
    member_role       BIGINT,
    partner_ping_role BIGINT,
    log_channel       BIGINT,
    partner_delay     INT
)

blacklists (
    guild_id   BIGINT PRIMARY KEY,
    reason     TEXT,
    added_by   BIGINT
)

whitelisted_links (
    link       TEXT PRIMARY KEY,
    added_by   BIGINT
)

early_access (
    guild_id   BIGINT PRIMARY KEY,
    user_id    BIGINT,
    reason     TEXT
)

premium (
    guild_id        BIGINT PRIMARY KEY,
    available_pings TEXT[],
    added_by        BIGINT,
    added_at        TIMESTAMPTZ DEFAULT NOW()
)
```

## Query Methods

| Method | Returns | Use for |
|--------|---------|---------|
| `fetchrow(sql, *args)` | single Record or `None` | lookup by PK |
| `fetch(sql, *args)` | list of Records | multi-row select |
| `fetchval(sql, *args)` | scalar or `None` | COUNT, single column |
| `execute(sql, *args)` | command tag string | INSERT/UPDATE/DELETE |
| `executemany(sql, [(args)])` | None | bulk insert/update |

Parameters always `$1, $2, ...` — never f-strings or `.format()`.

## Upsert Pattern

```python
await conn.execute("""
    INSERT INTO guild_config (guild_id, partner_channel)
    VALUES ($1, $2)
    ON CONFLICT (guild_id)
    DO UPDATE SET partner_channel = EXCLUDED.partner_channel
""", guild_id, channel_id)
```

## Transactions

```python
async with conn.transaction():
    await conn.execute("DELETE FROM premium WHERE guild_id = $1", guild_id)
    await conn.execute("INSERT INTO premium (guild_id, added_by) VALUES ($1, $2)", guild_id, user_id)
```

Rolls back automatically on any exception inside the block.

## Bulk Operations

```python
pairs = [(guild_id1, reason1), (guild_id2, reason2)]
await conn.executemany(
    "INSERT INTO blacklists (guild_id, reason) VALUES ($1, $2) ON CONFLICT DO NOTHING",
    pairs
)
```

## Row Access

```python
row = await conn.fetchrow("SELECT * FROM guild_config WHERE guild_id = $1", guild_id)
if row is None:
    return

channel_id = row["partner_channel"]
data = dict(row)  # for JSON serialization or passing to Redis
```

## Array Columns (PostgreSQL TEXT[])

```python
# Write
await conn.execute(
    "UPDATE premium SET available_pings = $1 WHERE guild_id = $2",
    ["none", "partner"],  # Python list → TEXT[]
    guild_id
)

# Read — comes back as Python list
pings = row["available_pings"]  # ["none", "partner"]
```

## Don't Query Config/Premium Directly

Use `bot.config.get(guild_id)` and `bot.premium.get(guild_id)` — they handle Redis cache and DB fallback. Only query `guild_config` or `premium` tables directly in `ConfigManager` / `PremiumManager` themselves.
