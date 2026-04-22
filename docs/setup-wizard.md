# Setup Wizard

## Overview

`/setup` walks a guild admin through all five config fields using Discord's native UI components (channel selects, role selects, buttons). All interaction is ephemeral. Times out after 5 minutes of inactivity.

Requires `Manage Guild`, `Administrator`, or bot owner (`has_management` check).

## Steps

1. **Welcome** — overview, Begin Setup button
2. **Log Channel** (Step 1/5) — `ChannelSelect`, text channels only. Private staff channel for bot warnings.
3. **Partner Channel** (Step 2/5) — `ChannelSelect`. Bot checks for `Send Messages` and `Mention Everyone` permissions immediately on selection. If missing, stays on this step with an explanation embed.
4. **Ad Channel** (Step 3/5) — `ChannelSelect`. Channel containing the server's advertisement message.
5. **Member Role** (Step 4/5) — `RoleSelect`. If selected role covers less than 95% of members, a warning is shown in the embed but the step is not blocked.
6. **Partner Ping Role** (Step 5/5) — `RoleSelect`. If coverage < 8%, a warning is shown.
7. **Review & Confirm** — shows all selections. Confirm or Cancel buttons.

## Validation on Confirm

Before saving, `validate_server` is called with the full config dict. If it returns a reason, a "Setup Failed" embed is shown and nothing is saved. The user must restart `/setup` to try again.

After saving, `partner_cog.index_ad(guild.id)` is called to immediately attempt to cache the guild's ad. The success embed's step 1 reflects the result — "Ad cached" if found, or a prompt to post an ad if not.

## State

`SetupState` is an in-memory object passed between views. It holds all five IDs as the user progresses. State is lost if the interaction times out.

## Notes

- Member role coverage warning thresholds in steps 4 and 5 read from `requirements.member_role_min_coverage` and `requirements.partner_role_min_coverage` in `config.yaml` — consistent with `validate_server`.
