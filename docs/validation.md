# Server Validation

## Overview

`validate_server(guild, config=None)` in `cogs/partner.py` checks whether a guild meets the requirements to participate in partner rounds. Returns `None` if valid, or a human-readable reason string if not.

It is used in three places:

1. `/config set` — before saving, if all three key fields are present in the merged config
2. `/setup` confirm step — before saving the full wizard config
3. Partner loop (`_run_partner_round`) — before adding a guild to the eligible pool

The site also calls it indirectly via the internal HTTP bridge.

## Thresholds

All thresholds come from `requirements` in `config.yaml`:

```yaml
requirements:
  member_role_min_coverage: 0.80   # 80% of members must have the member role
  channel_visibility_min: 0.95     # 95% of member-role members must see the partner channel
  partner_role_min_coverage: 0.08  # 8% of members must have the partner ping role
```

## Checks

In order:

1. **member_role resolves** — `guild.get_role(config["member_role"])` must return a role
2. **partner_ping_role resolves** — same
3. **partner_channel resolves** — `guild.get_channel(config["partner_channel"])` must return a channel
4. **Member role coverage** — `len(member_role.members) / guild.member_count >= member_role_min_coverage`
5. **Channel visibility** — of members with the member role, ≥95% must have `view_channel` permission in `partner_channel`
6. **Partner ping role coverage** — `len(partner_role.members) / guild.member_count >= partner_role_min_coverage`

The first failing check returns immediately with a reason. Checks are not accumulated.

## Optional Config Parameter

`validate_server(guild, config=None)` — if `config` is `None`, it fetches the current saved config from `ConfigManager`. Passing a config dict allows pre-save validation against an unsaved (merged) config, which is how `/config set`, `/setup`, and the site all use it.

## Internal HTTP Bridge

The site cannot call `validate_server` directly (separate process). The bot exposes:

```
POST http://app:8081/validate/{guild_id}
Body: {"config": {...merged config dict...}}
```

The bot calls `partner_cog.validate_server(guild, config)` and returns `{"reason": null}` (valid) or `{"reason": "string"}` (invalid).

The site fails open — if the bot is unreachable or times out (10s), the config is saved without validation.

## Dead Code

`check_partner_requirements` in `cogs/partner.py` is an older function that has `return True, None` as its first line. It is never called. It has slightly different thresholds (85% member role, hardcoded) and returns `(bool, reason)` instead of just `reason`. It should be deleted.
