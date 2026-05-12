# Early Access

## Overview

By default, the bot leaves any server with fewer than `requirements.minimum_membercount` members (currently 50). Early access bypasses this check for specific guilds.

## How It Works

On `on_guild_join`, the bot:

1. Checks `guild.member_count` against `requirements.minimum_membercount`
2. If below the minimum, checks Redis set `bot:early_access_guilds` for the guild ID
3. If not in the set, DMs the guild owner and leaves
4. If in the set, proceeds normally (adds to `bot:guild_ids`, allows config)

## Storage

- **Postgres**: `early_access` table (`guild_id`, `user_id`, `reason`)
- **Redis**: `bot:early_access_guilds` set — synced from Postgres on every `on_ready`

The Redis set is authoritative at runtime. On bot restart, `on_ready` clears and repopulates it from Postgres.

## Managing Early Access

All commands require bot owner. See [owner-tools.md](owner-tools.md) for full command details.

| Command | Effect |
|---------|--------|
| `/earlyaccess add <guild_id> <user> <reason>` | Insert into Postgres + Redis set |
| `/earlyaccess remove <guild_id>` | Delete from Postgres + Redis set |
| `/earlyaccess list` | List all records from Postgres |

## Notes

- Granting early access does not cause the bot to join the server — it only prevents it from leaving on next `on_guild_join`. The server owner still needs to add the bot manually.
- If the bot is already in a server and early access is revoked, the bot will not auto-leave — the check only runs on `on_guild_join`.
- `ON CONFLICT DO NOTHING` on insert — re-adding an already-granted server is a no-op. Use remove + add to update the reason or attributed user.
