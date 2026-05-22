# Schema Reference

Tables are defined in `schema.sql` at the repo root. `setup_hook` in `main.py` executes the file on every startup (`CREATE TABLE IF NOT EXISTS` — safe to re-run).

## Postgres Tables

### `guild_config`
| Column | Type | Notes |
|--------|------|-------|
| `guild_id` | `BIGINT` | PK |
| `partner_channel` | `BIGINT` | Channel ID where partner ads are posted |
| `ad_channel` | `BIGINT` | Channel ID containing the server's ad message |
| `member_role` | `BIGINT` | Role ID assigned to ≥80% of members |
| `partner_ping_role` | `BIGINT` | Role ID pinged on partner delivery |
| `log_channel` | `BIGINT` | Private staff channel for bot messages |
| `partner_delay` | `INTEGER` | Per-server cooldown in seconds. Default `21600` (6h). Range 3600–604800. Configurable via web panel. |
| `premium` | `BOOLEAN` | Default `false` |

### `blacklists`
| Column | Type | Notes |
|--------|------|-------|
| `guild_id` | `BIGINT` | PK |
| `reason` | `TEXT` | Required |
| `added_by` | `BIGINT` | Discord user ID of operator who added it |

### `whitelisted_links`
| Column | Type | Notes |
|--------|------|-------|
| `link` | `TEXT` | PK — stripped from ads before scan |
| `added_by` | `BIGINT` | Discord user ID of operator who added it |

### `early_access`
| Column | Type | Notes |
|--------|------|-------|
| `guild_id` | `BIGINT` | PK |
| `user_id` | `BIGINT` | Discord user ID of operator who granted access |
| `reason` | `TEXT` | Optional reason |

Grants a guild the ability to add the bot even if it is under `requirements.minimum_membercount` (default 50). See [early-access.md](early-access.md).

---

## Redis Keys

| Key | Type | TTL | Value | Set by |
|-----|------|-----|-------|--------|
| `bot:guild_ids` | Set | none | Guild IDs where bot is present | `main.py` on_ready / on_guild_join / on_guild_remove |
| `bot:early_access_guilds` | Set | none | Guild IDs with early access (bypass member count minimum) | `main.py` on_ready / `cogs/owneronly.py` earlyaccess commands |
| `bot:guild_info` | Hash | none | Field = `guild_id`, value = `{"name","icon","member_count"}` JSON | `main.py` on_ready / on_guild_join / on_guild_remove |
| `config:{guild_id}` | String | 30d | `guild_config` row as JSON | `src/configmanager.py` |
| `ads:{guild_id}` | String | none | Ping-stripped ad message text | `cogs/partner.py` index_ad / index_ads |
| `{claude_ver}:claude:{sha256_12}` | String | 30d | Claude Haiku scan result JSON `{sus,confidence,ai_hits,regex_hits,user_reason}` | `cogs/partner.py` scan_ad |
| `{cache_ver}:partner_cooldown:{min_id}:{max_id}` | String | 3d | `1` — signals cooldown active between two guilds | `cogs/partner.py` set_cooldown |
| `{cache_ver}:server_last_partner:{guild_id}` | String | none | Unix timestamp (float as string) of when this server last successfully partnered | `cogs/partner.py` partner |
| `last_partner_run` | String | 55s | `1` — distributed lock preventing multi-instance double-run | `cogs/partner.py` partner_loop |
| `invite:{channel_id}` | String | 6h | Discord invite URL for a partner channel | `cogs/owneronly.py` list_servers / debug_all_servers |
| `whitelisted_links` | Set | none | Link strings stripped from ads before scan | `cogs/partner.py` cog_load / `cogs/owneronly.py` |
| `panel:guilds:{user_id}` | String | 5m | JSON list of user's Discord guilds with permissions/counts | `site/app.py` _get_user_guilds |
| `ratelimit:get:{user_id}` | String | 60s | Request counter — max 30 GET requests/min | `site/app.py` _check_rate_limit |
| `ratelimit:config:{user_id}` | String | 60s | Request counter — max 10 config saves/min | `site/app.py` _check_rate_limit |
| `ratelimit:login:{ip}` | String | 60s | Request counter — max 10 `/login` requests/min per IP | `site/app.py` _check_rate_limit |
| `ratelimit:callback:{ip}` | String | 60s | Request counter — max 10 `/callback` requests/min per IP | `site/app.py` _check_rate_limit |

### Key format variables
- `{cache_ver}` — `config.yaml` → `cache.cache_version` (e.g. `v1`)
- `{claude_ver}` — `config.yaml` → `cache.claude_cache_version` (e.g. `v5`)
- `{sha256_12}` — first 12 chars of SHA-256 of the link-stripped ad text
