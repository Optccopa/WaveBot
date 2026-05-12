# Deployment

## Services

Defined in `docker/docker-compose.yaml`:

| Service | Image | Role |
|---------|-------|------|
| `app` | bot Dockerfile | Discord bot + internal validation HTTP server |
| `site` | site Dockerfile | Web panel (aiohttp) |
| `redis` | redis:7-alpine | Cache and inter-process locks |
| `postgres` | postgres:16-alpine | Persistent config and blacklist storage |

## Ports

- `app` exposes port `8081` internally (validation endpoint). Not published to host.
- `site` publishes its port externally (behind a reverse proxy).

`BOT_INTERNAL_URL=http://app:8081` is set on the site service so it can reach the bot.

## Restart Policy

`app` has `restart: always`. If the bot crashes, Docker restarts it automatically.

## Environment Variables

All secrets passed via environment. `POSTGRES_PASSWORD` is sourced from `${POSTGRES_PASSWORD}` in the compose file — must be set in the shell or a `.env` file.

### Bot (`app`)

| Variable | Required | Purpose |
|----------|----------|---------|
| `DISCORD_TOKEN` | yes | Bot login |
| `POSTGRES_PASSWORD` | yes | DB password |
| `POSTGRES_HOST` | no (default: `postgres`) | DB host |
| `POSTGRES_USER` | no (default: `appuser`) | DB user |
| `POSTGRES_DB` | no (default: `appdb`) | DB name |
| `ANTHROPIC_API_KEY` | yes | Claude Haiku for ad scanning |
| `LOG_WEBHOOK_URL` | no | Discord webhook for log forwarding (INFO+) |
| `BULK_LOG_WEBHOOK_URL` | no | Discord webhook for bulk/debug log forwarding (DEBUG+) |
| `BOT_INTERNAL_PORT` | no (default: `8081`) | Internal HTTP listen port |

### Site

| Variable | Required | Purpose |
|----------|----------|---------|
| `POSTGRES_PASSWORD` | yes | DB password |
| `DISCORD_CLIENT_ID` | yes | OAuth2 |
| `DISCORD_CLIENT_SECRET` | yes | OAuth2 |
| `DISCORD_REDIRECT_URI` | yes | OAuth2 callback |
| `SESSION_SECRET_KEY` | yes | Cookie encryption |
| `BOT_INTERNAL_URL` | no (default: `http://bot:8081`) | Bot validation endpoint |
| `PRODUCTION` | no (default: `false`) | Enables Secure cookies |

## Database Schema

Tables are created automatically on bot startup if they don't exist:

- `guild_config` — per-guild channel/role config
- `blacklists` — blacklisted guild IDs with reason
- `whitelisted_links` — links stripped from ads before scanning/storage
- `early_access` — guilds granted access below the minimum member count

## Shard Count

`AutoShardedBot` — Discord automatically determines shard count. No manual configuration needed.

## Config File

`config.yaml` is read at startup. Changes require a bot restart. Contains:

- `cache.cache_version` — prefix for Redis cooldown keys (bump to reset all cooldowns)
- `cache.claude_cache_version` — prefix for Claude scan result cache (bump to invalidate scan results)
- `cache.pipeline_batch` — Redis pipeline batch size for ad writes
- `cache.redis_lock` — TTL for the inter-instance partner loop lock (seconds, default 19800)
- `cache.partner_cooldown` — TTL for partner pair cooldowns (seconds, default 259200 = 3 days)
- `cache.invite` — TTL for cached Discord invite URLs in Redis (seconds, default 21600 = 6h)
- `delays.partner_pair` — sleep between each partner pair send (seconds, default 3)
- `delays.scan_ad` — sleep after each Anthropic API scan call (seconds, default 1)
- `delays.invite_fetch` — sleep after each Discord invite API call in owner commands (seconds, default 1)
- `bot.support_invite` — support server invite URL used in DMs
- `requirements.*` — validation thresholds for `validate_server`
