# Web Panel

## Overview

`site/app.py` is an aiohttp web application serving the guild configuration dashboard. It is a separate Docker service (`site`) that talks to the bot service (`app`) via an internal HTTP endpoint.

## Authentication

Discord OAuth2 (`identify guilds` scopes). Flow:

1. `/login` — generates CSRF state, redirects to Discord OAuth
2. `/callback` — exchanges code for token, fetches user info, stores in encrypted cookie session. Session is invalidated and regenerated on login to prevent session fixation.
3. `/logout` — CSRF-protected POST, invalidates session

Sessions use `EncryptedCookieStorage` with a SHA-256 derived key from `SESSION_SECRET_KEY`. Cookie is `HttpOnly`, `SameSite=Lax`, `Secure` when `PRODUCTION=true`.

## Authorization

Only guilds where the user has `Manage Guild` AND the bot is present are shown. Bot guild membership is checked via `bot:guild_ids` Redis set (populated by the bot on ready and guild join/leave events).

## Rate Limiting

- GET routes: 30 requests/minute per user (`ratelimit:get:{user_id}`)
- Config save: 10 saves/minute per user (`ratelimit:config:{user_id}`)

Implemented with atomic Redis SET NX + INCR to avoid race conditions.

## Config Save Flow (`POST /server/{guild_id}`)

1. CSRF token verified
2. Rate limit checked
3. Form fields validated as Discord snowflakes (15–21 digit integers)
4. If all three key fields present in merged config, calls bot's internal validation endpoint
5. If validation fails, re-renders page with `validation_error` alert
6. If validation passes, saves via `ConfigManager.set`
7. Redirects to `?saved=1`

The validation call to the bot fails open — if the bot is unreachable, config is saved without validation.

## Security Headers

Applied to every response via middleware:

- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy: default-src 'self'; img-src 'self' https://cdn.discordapp.com data:; style-src 'self'; script-src 'none'`

## Guild List Caching

User's guild list from Discord API is cached in Redis at `panel:guilds:{user_id}` for 5 minutes to avoid hammering the Discord API on each page load.

## Bot Info Cache

Guild names/icons/member counts are cached in Redis hash `bot:guild_info` (keyed by guild ID, JSON values). Populated by the bot on ready and guild join events.

## Environment Variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `POSTGRES_HOST` | `postgres` | DB host |
| `POSTGRES_USER` | `appuser` | DB user |
| `POSTGRES_PASSWORD` | required | DB password |
| `POSTGRES_DB` | `appdb` | DB name |
| `REDIS_HOST` | `redis` | Redis host |
| `DISCORD_CLIENT_ID` | required | OAuth2 app |
| `DISCORD_CLIENT_SECRET` | required | OAuth2 app |
| `DISCORD_REDIRECT_URI` | required | OAuth2 callback URL |
| `SESSION_SECRET_KEY` | required | Cookie encryption key |
| `BOT_INTERNAL_URL` | `http://bot:8081` | Internal bot validation URL |
| `PRODUCTION` | `false` | Enables Secure cookies |
| `PANEL_PORT` | `8080` | Listen port |
