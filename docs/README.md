# WaveBot Documentation Index

Quick navigation to all documentation. Start with **Overview** or jump to your topic.

## Overview

- **[PARTNER_SYSTEM.md](PARTNER_SYSTEM.md)** — Quick reference for how the partner system works, timing, commands
- **[CONFIG.md](CONFIG.md)** — How to configure the bot (channels, roles, delays)

## Partner System (Detailed)

- **[partner-loop-flow.md](partner-loop-flow.md)** — Complete 6-phase execution walkthrough
  - Ad indexing, eligibility filtering, matching, sat-out reroll, sending, cleanup
  - Data structures, state flow diagram, edge cases, performance notes
- **[partner-matching.md](partner-matching.md)** — Matching algorithm and cooldown strategy
  - Eligibility criteria, greedy maximum matching, sat-out reroll logic
  - Concurrency and locking
- **[known-issues.md](known-issues.md)** — Known limitations and architectural constraints

## Infrastructure & Operations

- **[logging.md](logging.md)** — Logging system, webhook handler, error tracking
- **[deployment.md](deployment.md)** — Deployment and configuration
- **[schema.md](schema.md)** — Database schema and key definitions
- **[setup-wizard.md](setup-wizard.md)** — Interactive setup flow for server admins

## Features

- **[ad-scanning.md](ad-scanning.md)** — Ad content scanning and moderation
- **[config-management.md](config-management.md)** — Config storage and caching strategy
- **[validation.md](validation.md)** — Server validation rules and checks

## Web Panel

- **[web-panel.md](web-panel.md)** — Web UI features and usage

---

## Quick Links by Task

### "I'm a server admin setting up the bot"
→ Start with [CONFIG.md](CONFIG.md), then run `/setup`

### "I want to understand how matching works"
→ Read [partner-matching.md](partner-matching.md) then [partner-loop-flow.md](partner-loop-flow.md)

### "I need to debug why my server isn't getting partners"
→ Check [partner-matching.md](partner-matching.md#eligibility), then `/partner status`

### "I'm deploying/hosting the bot"
→ See [deployment.md](deployment.md) and [schema.md](schema.md)

### "I'm developing new features"
→ Read [partner-loop-flow.md](partner-loop-flow.md) for loop context, check [known-issues.md](known-issues.md) for constraints

### "Something went wrong, I need logs"
→ See [logging.md](logging.md) for webhook handler and error tracking

### "How is config stored?"
→ [config-management.md](config-management.md)

---

## Recent Updates (2026-04-27)

- ✅ Fixed critical partner system issues (fixes 4, 5, 6) — see [partner-fixes-2026-04-27.md](../audits/partner-fixes-2026-04-27.md)
- ✅ Added [partner-loop-flow.md](partner-loop-flow.md) — comprehensive 6-phase walkthrough
- ✅ Updated [known-issues.md](known-issues.md) — removed fixed issues, added known limitations
- ✅ Simplified [PARTNER_SYSTEM.md](PARTNER_SYSTEM.md) — quick reference instead of detailed flow
