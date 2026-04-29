# Config Management

## Storage

Config is stored in Postgres table `guild_config`:

```
guild_id          BIGINT PRIMARY KEY
partner_channel   BIGINT
ad_channel        BIGINT
member_role       BIGINT
partner_ping_role BIGINT
log_channel       BIGINT
premium           BOOLEAN DEFAULT FALSE
```

## Caching

`ConfigManager` (`src/configmanager.py`) wraps all access with Redis caching.

- **Get**: checks `config:{guild_id}` in Redis first. On cache miss, reads from Postgres and writes to Redis with 30-day TTL.
- **Set**: upserts into Postgres, then invalidates the Redis key and immediately re-reads from Postgres to repopulate the cache. This avoids a stale read-merge-write race.
- **Invalidate**: deletes `config:{guild_id}` from Redis.

Corrupted cache values (bad JSON) are deleted on read so the next call falls through to Postgres cleanly.

## Allowed Fields

Only fields in `ALLOWED_COLUMNS` can be set via `ConfigManager.set`:

```python
{"partner_channel", "ad_channel", "member_role", "partner_ping_role", "log_channel"}
```

`premium` is not settable through the ConfigManager API — it must be set directly in Postgres.

## Validation on Write

Both the bot (`/config set`) and site (`POST /server/{guild_id}`) validate before saving when the three key fields are all present in the merged config:

- `member_role`
- `partner_ping_role`
- `partner_channel`

If validation fails, the config is NOT saved and the reason is returned to the user.

See [validation.md](validation.md) for thresholds and logic.

## Bot Command — `/config set`

`cogs/config.py`. Requires `Manage Guild`, `Administrator`, or bot owner (`has_management` check). Cooldown: 1 use per 10 seconds per user. Accepts any subset of the five config fields as Discord channel/role pickers. Merges submitted fields with existing config, validates if all three key fields are present, saves if valid.

If `ad_channel` is in the updated fields, `partner_cog.index_ad(guild_id)` is called after saving. The confirmation message indicates whether the ad was cached successfully or not found.

## Site

See [web-panel.md](web-panel.md) for site-side config management.
