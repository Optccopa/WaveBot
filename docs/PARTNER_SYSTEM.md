# Partner System — Overview

This is a quick reference. For detailed execution flow, see `partner-loop-flow.md`. For matching algorithm details, see `partner-matching.md`.

## How It Works

Every 6 hours, the bot:
1. Indexes all server ads from Discord channels
2. Filters eligible servers (valid config, no cooldown, no personal delay)
3. Pairs servers using greedy maximum matching
4. Sends each server's ad to their partner's partner channel with an appropriate ping
5. Sets a 3-day cooldown and per-server delay to prevent rapid re-pairing

## Timing

- **Loop interval:** 6 hours (21600 seconds) — not configurable without code changes
- **Pairwise cooldown:** 3 days (259200 seconds) — prevents same pair within 3 days
- **Per-server delay:** Configurable per server, default 6 hours, range 1 hour–7 days
- **Distributed lock:** 3 hours (10800 seconds) — blocks other instances if one crashes

## Configuration

```
/config set partner_channel <#channel>    # Where to post received ads
/config set ad_channel <#channel>         # Where your ad is posted
/config set member_role <@role>           # Role for active members (≥80% coverage)
/config set partner_ping_role <@role>     # Role to ping on new partners (≥8% coverage)
/config set log_channel <#channel>        # Optional: errors logged here
/config set partner_delay <seconds>       # Optional: 3600–604800s, default 21600
```

## Partnership Requirements

All of these must be true:
- Config is complete (all required fields set)
- Member role covers ≥80% of members
- Partner ping role covers ≥8% of members
- Partner channel is visible to member role
- Bot has Send Messages + Mention Everyone in partner channel
- Server is not blacklisted
- Server has no active pairwise cooldown with any potential partner
- Server has no active personal delay (last_partnered key)

## Commands

- `/partner status` — See eligibility issues
- `/partner loopinfo` — When's next run?
- `/partner force <id1> <id2>` — Admin: force a pair now
- `/partner loopforce` — Admin: run loop immediately
- `/partner ad <guild_id>` — Admin: view cached ad

## See Also

- `partner-loop-flow.md` — Complete execution walkthrough (phases 1–6)
- `partner-matching.md` — Matching algorithm and cooldown strategy
- `known-issues.md` — Known limitations
- `CONFIG.md` — Full config option reference
