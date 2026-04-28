# The Council of 5 — Code Review System

The Council of 5 is a multi-angle code review system that spawns five specialized subagents to review code and pull requests from different perspectives. Each reviewer focuses on a specific domain to catch issues that a single reviewer might miss.

## The Five Roles

### 1. Logic & Production Performance
**Responsibility:** Validates algorithmic correctness and runtime efficiency

Reviews for:
- Logical correctness of algorithms (match algo, partnership logic, etc.)
- O(n) complexity analysis and performance bottlenecks
- Memory leaks and resource cleanup
- Unnecessary iterations, redundant operations, or inefficient data structures
- Cache hit rates and Redis usage patterns
- Database query optimization (N+1 queries, missing indexes)
- Async/await correctness (deadlocks, race conditions)
- Whether the code prioritizes runtime speed per CLAUDE.md guidelines

**Questions asked:**
- Does the code do what it's supposed to do?
- Are there obvious performance issues?
- Will this scale with 10k servers? 100k servers?
- Are we efficiently using Redis and Postgres?

---

### 2. Security
**Responsibility:** Identifies vulnerabilities and security risks

Reviews for:
- SQL injection, command injection, prompt injection
- Rate limiting and cooldown enforcement
- Authentication/authorization bypass opportunities
- Data exposure (logging secrets, error messages leaking info)
- Malicious input handling and validation
- Privilege escalation vectors
- Unsafe deserialization or untrusted data parsing
- OWASP Top 10 violations
- Blacklist/whitelist bypass opportunities

**Questions asked:**
- Can a malicious user break this?
- Are secrets safe from logs and error messages?
- Is input validated properly?
- Do we enforce rate limits and permissions correctly?

---

### 3. Discord.py API Conventions
**Responsibility:** Ensures correct Discord API usage and framework patterns

Reviews for:
- Correct use of discord.py decorators and contexts
- Proper error handling for Discord API calls
- Correct permission checks and Discord.abc patterns
- Async context management and interaction lifecycle
- Message/embed formatting and limits (2000 char, embed constraints)
- Command cooldown implementation
- Proper use of views, modals, and buttons
- Event listener correctness
- Intents configuration and gateway event handling
- Best practices from discord.py documentation

**Questions asked:**
- Does this follow discord.py patterns?
- Are we handling interactions correctly?
- Will Discord API reject this?
- Is the code resilient to Discord rate limits?

---

### 4. Data Integrity & Architecture
**Responsibility:** Validates database design, data consistency, and architectural coherence

Reviews for:
- Postgres schema correctness and consistency
- Transaction boundaries and ACID compliance
- Cache invalidation correctness
- Redis expiration strategy (are TTLs correct?)
- Data synchronization between Postgres and Redis
- Distributed system consistency (multi-instance conflicts)
- Blacklist/whitelist enforcement across instances
- Config consistency between cache and database
- Migration strategy and backward compatibility
- Whether persisted data aligns with CLAUDE.md requirements

**Questions asked:**
- Is the data consistent across Postgres and Redis?
- What happens if the bot crashes mid-operation?
- Do we handle concurrent writes correctly?
- Are TTLs and expiration times correct?

---

### 5. Testing & Reliability
**Responsibility:** Assesses robustness, error handling, and test coverage

Reviews for:
- Error handling completeness (what happens when Redis is down? Discord API fails?)
- Graceful degradation and fallback behavior
- Edge cases and boundary conditions
- Timeout handling and deadlock prevention
- Logging quality (is debugging this easy?)
- Exception handling and recovery
- State consistency after failures
- Whether critical paths have test coverage
- Observability and monitorability

**Questions asked:**
- What happens when things go wrong?
- How do we know if this is broken in production?
- Are edge cases handled?
- Will this be easy to debug?

---

## How to Invoke the Council

### Option 1: Manual Agent Spawn
Spawn five agents in parallel, one for each role:

```
Agent({
  subagent_type: "general-purpose",
  prompt: "Review this code for Logic & Production Performance issues..."
})

Agent({
  subagent_type: "general-purpose",
  prompt: "Review this code for Security vulnerabilities..."
})
# ... repeat for remaining 3 roles
```

### Option 2: Single Council Command
Request the council as a unified review:

```
/council <file_or_pr>
```

This spawns all five agents in parallel and collates their findings.

## Council Review Output

Each agent returns a review with:
- **Issues Found** — specific problems in priority order (critical, high, medium, low)
- **Recommendations** — how to fix each issue
- **Questions for Author** — clarifications needed
- **Approval** — green/yellow/red (approve/needs changes/block)

The council consensus determines final merge readiness.

## Example Council Review Sections

### From Logic & Performance Agent
```
**Critical:** partner_loop calls redis.exists() for each pair individually instead of using pipeline. 
With 10k servers, this is ~50M Redis calls per loop. Use pipeline.execute() to batch.

**High:** get_req() recalculates tiers every call. Cache tier results for reference scales.
```

### From Security Agent
```
**Critical:** parse_ping() has a placeholder that always returns a testing string. 
This bypasses actual role pinning. Remove test code before merging.

**High:** validate_server() doesn't rate-limit failed validation attempts.
Add cooldown to prevent validation bruteforcing.
```

### From Discord.py Agent
```
**Medium:** Using embed.add_field() in a loop without checking embed size (20-field limit).
Long issue lists will silently truncate. Check len(embed.fields) before adding.

**Low:** Cooldown message should use interaction.response.defer() first.
Current code might timeout before sending response.
```

### From Data Integrity Agent
```
**High:** Cache version in config.yaml changed, but old keys in Redis not invalidated.
Add migration script or set longer TTLs to prevent cache misses.

**Medium:** last_partnered:{guild_id} TTL is per-server but cooldown TTL is global.
Document the 3-day vs. 6-hour difference clearly.
```

### From Testing & Reliability Agent
```
**High:** partner() function returns (None, None) on failure but callers don't validate before using.
Should raise exception or use Optional type hints.

**Medium:** index_ads() silently skips servers with missing channels. Log warnings or send to log_channel.
```

## Council Decision Logic

| All agents approve | 4 agents approve | 3 agents approve | Fewer approve |
|---|---|---|---|
| **✅ Merge** — clear | **✅ Merge** — one concern noted | **⚠️ Review** — multiple concerns | **❌ Block** — significant issues |

If any agent rates something as **Critical**, the PR is blocked regardless of other approvals.

---

## Notes for Council Members

- Be specific with line numbers and code snippets
- Distinguish between "must fix" and "nice to have"
- Consider the project's priorities (speed > elegance per CLAUDE.md)
- Look for patterns, not just individual lines
- Challenge architectural decisions, not just syntax
- Assume the author is competent; focus on blind spots

---

**The Council of 5 brings five perspectives to one problem. No single view catches everything.**