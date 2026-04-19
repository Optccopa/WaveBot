# Schema Reference

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

---

## Redis Keys

| Key | Type | TTL | Value | Set by |
|-----|------|-----|-------|--------|
| `bot:guild_ids` | Set | none | Guild IDs where bot is present | `main.py` on_ready / on_guild_join / on_guild_remove |
| `bot:guild_info` | Hash | none | Field = `guild_id`, value = `{"name","icon","member_count"}` JSON | `main.py` on_ready / on_guild_join / on_guild_remove |
| `config:{guild_id}` | String | 30d | `guild_config` row as JSON | `src/configmanager.py` |
| `ads:{guild_id}` | String | none | Ping-stripped ad message text | `cogs/cache_ads.py` ad_loop |
| `{claude_ver}:claude:{sha256_12}` | String | 30d | Claude Haiku scan result JSON `{sus,confidence,ai_hits,regex_hits,user_reason}` | `cogs/cache_ads.py` scan_ad |
| `{cache_ver}:partner_cooldown:{min_id}:{max_id}` | String | 3d | `1` — signals cooldown active between two guilds | `cogs/partner.py` set_cooldown |
| `last_partner_run` | String | 3h | `1` — distributed lock preventing multi-instance double-run | `cogs/partner.py` partner_loop |
| `whitelisted_links` | Set | none | Link strings stripped from ads before scan | `cogs/cache_ads.py` cog_load / `cogs/owneronly.py` |
| `panel:guilds:{user_id}` | String | 5m | JSON list of user's Discord guilds with permissions/counts | `site/app.py` _get_user_guilds |
| `ratelimit:get:{user_id}` | String | 60s | Request counter — max 30 GET requests/min | `site/app.py` _check_rate_limit |
| `ratelimit:config:{user_id}` | String | 60s | Request counter — max 10 config saves/min | `site/app.py` _check_rate_limit |

### Key format variables
- `{cache_ver}` — `config.yaml` → `cache.cache_version` (e.g. `v1`)
- `{claude_ver}` — `config.yaml` → `cache.claude_cache_version` (e.g. `v5`)
- `{sha256_12}` — first 12 chars of SHA-256 of the link-stripped ad text
