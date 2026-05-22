# Commands Reference

## Prefix Commands (`p!` prefix)

| Command | Access | Cooldown | Description |
|---------|--------|----------|-------------|
| `p!ping` | Public | 1/10s | Bot latency, Discord API latency, DB latency, Redis latency |
| `p!help` | Public | 1/10s | Lists all commands grouped by access level |
| `p!exec <code>` | Bot owner | 1/10s | Execute arbitrary async Python in bot context — see [owner-tools.md](owner-tools.md) |

## Slash Commands

### Public

| Command | Cooldown | Description |
|---------|----------|-------------|
| `/bot info` | 1/10s | Bot stats: server count, total members, stack, support invite |
| `/partner loopinfo` | 1/10s | Whether the partner loop is running, failed, and next scheduled run time |
| `/partner reqs [membercount]` | 1/10s | Ping tier breakdown for a given server size (default 1000). Shows which guest size ranges map to which ping types |
| `/partner ad <guild_id>` | 1/10s | View cached ad text for a server. Tries `index_ad` on cache miss before returning |

### Management (requires `Manage Guild` or `Administrator`)

| Command | Cooldown | Description |
|---------|----------|-------------|
| `/partner status` | 1/10s | Shows why your server may not be getting partnered (blacklist, missing config, missing ad, failed validation) |
| `/config set [...]` | 1/10s | Set one or more config fields. Any subset is valid. Checks bot permissions in partner_channel before saving. Shows coverage warnings if member_role or partner_ping_role are below thresholds. Validates before saving if all three key fields are present. Re-indexes ad if `ad_channel` changes |
| `/config view` | 1/10s | View current server config — all five fields plus premium status |
| `/setup` | 1/10s | Interactive 5-step setup wizard using Discord UI components |

### Owner Only

All owner commands require `is_owner()` (bot application owner check).

| Command | Description |
|---------|-------------|
| `/partner force <id1> <id2>` | Force a partner send between two specific servers immediately |
| `/partner loopforce` | Run a full partner round immediately. Acquires the asyncio lock; does not skip the Redis NX check |
| `/partner indexads` | Re-index all server ads. Returns summary: total, cached, missing ad, missing channel, no config |
| `/partner broadcast <guild_id>` | Send a server's cached ad to every other server's partner channel. 24h command cooldown |
| `/error` | View the last recorded error for slash commands, prefix commands, and events |
| `/servers overview` | All servers with member count, needs/week, available partners/week, and next eligible timestamp. Paginated in chunks of 25 |
| `/servers debug <server_id>` | Detailed debug embed for one server: config JSON, channel/role resolution, ad cache, invite |
| `/servers debugall` | Debug embeds for every server the bot is in |
| `/servers leave <server_id>` | Force the bot to leave a server |
| `/servers invite <server_id>` | Get an invite to a server. Uses partner channel first, falls back to any channel the bot can create invites in |
| `/blacklist add <guild_id> <reason>` | Blacklist a server. Bot leaves immediately if currently in it |
| `/blacklist remove <guild_id>` | Remove a server from the blacklist |
| `/blacklist check <guild_id>` | Check whether a server is blacklisted and view the reason |
| `/whitelist add <link>` | Whitelist a link so it is stripped from ads before scanning |
| `/whitelist remove <link>` | Remove a link from the whitelist |
| `/whitelist list` | List all whitelisted links |
| `/earlyaccess add <guild_id> <user> <reason>` | Grant a server early access to bypass the minimum member count |
| `/earlyaccess remove <guild_id>` | Revoke early access from a server |
| `/earlyaccess list` | List all servers with early access |

## Notes

- All slash command cooldowns are per-user, not per-guild.
- The `userloop` background task (every 5 minutes) automatically assigns/removes the `bot_user` role in the support server based on whether a member owns a server that has the bot.
