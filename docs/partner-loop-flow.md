# Partner Loop Flow

Complete execution flow of the 6-hour partner matching cycle.

## Loop Trigger

```
Every 21600 seconds (6 hours)
  └─ @tasks.loop(seconds=21600) partner_loop()
     └─ Runs in background, non-blocking
     └─ before_loop waits for bot.wait_until_ready()
```

## Concurrency Gates

**Within single instance (asyncio.Lock):**
```
if self._partner_lock.locked():
  └─ Skip (already running)
else:
  └─ Acquire lock
  └─ Try to acquire Redis distributed lock
     └─ SET last_partner_run NX EX 10800s
     └─ If fails (another instance has lock)
        └─ Release asyncio lock
        └─ Skip this cycle
```

## Phase 1: Ad Indexing

**Refresh all server ads from Discord channels.**

```
index_ads():
  ├─ For each guild in bot.guilds:
  │  ├─ Fetch config from DB/Redis
  │  │  └─ config.get(guild_id)
  │  ├─ Get ad_channel from guild
  │  ├─ Scan recent 10 messages for link (LINK_REGEX)
  │  ├─ Strip whitelisted links from ad text
  │  ├─ Check Claude scan cache
  │  │  └─ Key: {claude_cache_version}:claude:{ad_hash}
  │  │  └─ TTL: 2592000s (30 days)
  │  ├─ If not cached:
  │  │  ├─ Call scan_ad(ad_text) → Claude Haiku AI
  │  │  │  ├─ Regex prescan (RULE_PATTERNS)
  │  │  │  ├─ If regex hit → reject (sus:true)
  │  │  │  └─ Else → Claude eval (max_tokens:256, temp:0.1)
  │  │  │     └─ Timeout: 30s
  │  │  │     └─ On timeout → sus:false (accept suspicious ad, safety tradeoff)
  │  │  ├─ Cache result with TTL
  │  ├─ Strip pings from ad (@everyone, @here, <@&role>)
  │  ├─ Add to pending batch: (ads:{guild_id}, ad_text)
  │  ├─ Log to log_channel if error
  │  │  └─ Missing ad_channel embed
  │  │  └─ Missing ad message embed
  │  
  ├─ Batch write all pending ads to Redis
  │  ├─ batch_size from config.yaml (default 250)
  │  ├─ For each batch:
  │  │  ├─ Pipeline SET ads:{guild_id} ad_text
  │  │  ├─ On failure:
  │  │  │  └─ Log error with batch range
  │  │  │  └─ Continue to next batch (fail-forward)
  │  ├─ Count only successful batches in summary
  │  
  └─ Return summary:
     ├─ total: all guilds in bot
     ├─ cached: successfully indexed ads
     ├─ missing_ad: no recent message with link
     ├─ missing_channel: ad_channel not configured
     └─ no_config: guild not configured
```

**Summary stored in-memory, used for logging only.**

---

## Phase 2: Eligibility Filtering

**Build list of guilds eligible for matching.**

```
For each guild in bot.guilds:
  
  ├─ BLACKLIST CHECK
  │  └─ Fetch from blacklists table
  │     └─ If guild_id in blacklist → SKIP
  │
  ├─ CONFIG CHECK
  │  ├─ config = await bot.config.get(guild_id)
  │  └─ If no config → SKIP
  │
  ├─ RESOLVE DISCORD OBJECTS
  │  ├─ partner_channel = guild.get_channel(config['partner_channel'])
  │  ├─ ad_channel = guild.get_channel(config['ad_channel'])
  │  ├─ member_role = guild.get_role(config['member_role'])
  │  ├─ partner_ping_role = guild.get_role(config['partner_ping_role'])
  │  └─ Any None → SKIP + send error embed to log_channel
  │
  ├─ CHANNEL TYPE CHECK
  │  └─ if not isinstance(partner_channel, discord.TextChannel) → SKIP
  │
  ├─ PERMISSIONS CHECK
  │  ├─ perms = partner_channel.permissions_for(guild.me)
  │  ├─ Need: send_messages AND mention_everyone
  │  └─ If missing → SKIP + send embed to log_channel
  │
  ├─ AD CACHE CHECK
  │  ├─ ad = await redis.get(f'ads:{guild.id}')
  │  └─ If not in Redis → SKIP (will be indexed next cycle)
  │
  ├─ VALIDATION CHECK
  │  ├─ validate_server(guild, config):
  │  │  ├─ member_role coverage ≥ 80%
  │  │  ├─ partner_channel visibility ≥ 95%
  │  │  └─ partner_ping_role coverage ≥ 8%
  │  └─ If fails → SKIP + send embed to log_channel
  │
  ├─ PERSONAL DELAY CHECK
  │  ├─ last_partnered:{guild_id} exists in Redis?
  │  └─ If yes (server was recently partnered) → SKIP
  │
  └─ ✅ ELIGIBLE
     └─ Add to available: (guild_id, member_count)
```

**Result: `available = [(guild_id, member_count), ...]`**

---

## Phase 3: Greedy Maximum Matching

**Pair up eligible servers using greedy algorithm.**

```
match_servers(available):
  
  ├─ pool = [guild_id for guild_id, _ in available]
  ├─ Shuffle pool randomly
  │
  ├─ Generate all possible pairs
  │  └─ all_pairs = [(min(a,b), max(a,b)) for all a,b in pool where a < b]
  │
  ├─ COOLDOWN CHECK (one Redis pipeline)
  │  ├─ For each pair:
  │  │  ├─ Key: {cache_version}:partner_cooldown:{a}:{b}
  │  │  └─ Check EXISTS
  │  ├─ Collect results (order preserved)
  │  
  ├─ BUILD ADJACENCY GRAPH
  │  ├─ neighbors: dict[guild_id → set[partner_guild_ids]]
  │  └─ Add edge (a↔b) only if NOT on cooldown
  │
  ├─ SORT BY CONSTRAINT (Most constrained first)
  │  └─ Sort pool by len(neighbors[guild_id])
  │     └─ Guild with fewest available partners gets priority
  │
  ├─ GREEDY MATCHING
  │  ├─ matched = set()
  │  ├─ pairs = []
  │  ├─ For each server in sorted order:
  │  │  ├─ If server already matched → continue
  │  │  ├─ available = neighbors[server] - matched
  │  │  ├─ If available is empty → skip (sat-out)
  │  │  ├─ Pick partner = min(available, key=len(neighbors[x] - matched))
  │  │  │  └─ Choose partner with fewest remaining options
  │  │  ├─ pairs.append((server, partner))
  │  │  └─ matched.add(server, partner)
  │  
  ├─ SAT-OUT SERVERS
  │  └─ sat_out = [s for s in pool if s not in matched]
  │
  └─ Return (pairs, sat_out)
```

**Note: Greedy matching is O(n²) for pair generation, O(n) for matching itself.**

---

## Phase 4: Sat-Out Reroll (If ≥2 servers unmatched)

**Clear inter-cooldowns for unmatched servers and retry.**

```
if len(sat_out) >= 2:
  
  ├─ Generate sat_pairs (all pairs within sat_out)
  │
  ├─ ATOMIC CLEAR (transaction=True)
  │  ├─ MULTI
  │  ├─ For each pair:
  │  │  └─ DELETE {cache_version}:partner_cooldown:{a}:{b}
  │  └─ EXEC (all-or-nothing)
  │     └─ On failure → log error, abort entire sat-out logic
  │
  ├─ RETRY MATCHING
  │  └─ match_servers([(s, available_map[s]) for s in sat_out])
  │     └─ Now pairs without cooldown interference
  │
  ├─ If retry produces NEW pairs:
  │  └─ Extend main pairs list
  │
  ├─ If retry produces NO pairs:
  │  ├─ ATOMIC RESTORE (transaction=True)
  │  ├─ MULTI
  │  ├─ For each pair:
  │  │  └─ SET {cache_version}:partner_cooldown:{a}:{b} 1 EX 259200s
  │  └─ EXEC (all-or-nothing)
  │     └─ On failure → log warning, cooldowns stay deleted
  │
  └─ Log remaining unmatched servers
```

**Note: One-time reroll per cycle. If retry still produces unmatched, they wait for next cycle.**

---

## Phase 5: Partnership Execution

**Send ads between paired servers.**

```
For each pair (server1_id, server2_id):
  
  ├─ FETCH CONFIGS
  │  ├─ config1 = await bot.config.get(server1_id)
  │  ├─ config2 = await bot.config.get(server2_id)
  │  └─ If either missing → abort pair, return (None, None)
  │
  ├─ RESOLVE GUILDS & CHANNELS
  │  ├─ guild1 = bot.get_guild(server1_id)
  │  ├─ guild2 = bot.get_guild(server2_id)
  │  ├─ channel1 = guild1.get_channel(config1['partner_channel'])
  │  ├─ channel2 = guild2.get_channel(config2['partner_channel'])
  │  └─ If any None → abort pair, return (None, None)
  │
  ├─ CALCULATE PING TIERS
  │  ├─ get_req(guild1.member_count, guild2.member_count)
  │  │  ├─ Determine host (larger) and guest (smaller)
  │  │  ├─ REF = 2300 members
  │  │  ├─ scale = host_count / REF
  │  │  ├─ Tiers (scaled by size difference):
  │  │  │  ├─ ≤400: host_ping = "none"
  │  │  │  ├─ ≤800: host_ping = "partner"
  │  │  │  ├─ ≤1700: host_ping = "here"
  │  │  │  ├─ ≤2000: host_ping = "partnerhere"
  │  │  │  └─ >2000: host_ping = "member"
  │  │  └─ guest_ping = always "member"
  │  │
  │  └─ Result: {server_a_ping, server_b_ping, host}
  │
  ├─ FETCH ADS
  │  ├─ raw_ad1 = redis.get(f'ads:{server1_id}')
  │  ├─ raw_ad2 = redis.get(f'ads:{server2_id}')
  │  └─ If either missing → abort pair (will be indexed next cycle)
  │
  ├─ PARSE PINGS
  │  ├─ ping1 = parse_ping(server2_id, r['server_b'])
  │  │  └─ ⚠️ CURRENTLY RETURNS PLACEHOLDER (test code not removed)
  │  ├─ ping2 = parse_ping(server1_id, r['server_a'])
  │  └─ Result: role mentions or @here or "" (empty)
  │
  ├─ BUILD FINAL ADS
  │  ├─ ad1 = raw_ad1 + "\n\n" + ping1
  │  ├─ ad2 = raw_ad2 + "\n\n" + ping2
  │  └─ Length check: both ≤ 2000 chars (Discord limit)
  │     └─ If too long → abort pair
  │
  ├─ SET COOLDOWN (BEFORE SENDS to prevent livelock)
  │  ├─ set_cooldown(server1_id, server2_id)
  │  └─ Key: {cache_version}:partner_cooldown:{min}:{max}
  │     └─ TTL: 259200s (3 days)
  │
  ├─ SEND ADS WITH BACKOFF
  │  ├─ Create view = AddBotView() (single instance)
  │  │
  │  ├─ _send_with_backoff(channel1, ad2, view, server1_id, channel1.name):
  │  │  ├─ For attempt in range(3):
  │  │  │  ├─ Try: channel.send(ad2, view=view)
  │  │  │  ├─ On discord.HTTPException status=429:
  │  │  │  │  ├─ wait_time = (2^attempt) * 5 seconds
  │  │  │  │  ├─ 5s, 10s, 20s for attempts 0,1,2
  │  │  │  │  └─ await asyncio.sleep(wait_time)
  │  │  │  ├─ On other HTTP error:
  │  │  │  │  └─ Log error, return False immediately
  │  │  │  └─ On success: return True
  │  │  └─ After max retries: log failure, return False
  │  │
  │  ├─ If send1 fails:
  │  │  └─ return (None, None) [cooldown already set]
  │  │
  │  ├─ _send_with_backoff(channel2, ad1, view, server2_id, channel2.name)
  │  │  └─ Same backoff logic
  │  │
  │  └─ If send2 fails:
  │     └─ return (None, None) [cooldown already set]
  │
  ├─ SET PERSONAL DELAYS
  │  ├─ Fetch partner_delay from both configs
  │  │  └─ Default: 21600s (6 hours)
  │  │  └─ Clamp: [3600s, 604800s] (1 hour to 7 days)
  │  │
  │  ├─ last_partnered:{server1_id} SET 1 EX delay_a
  │  └─ last_partnered:{server2_id} SET 1 EX delay_b
  │     └─ Prevents same server from getting another partner for delay_a/delay_b
  │
  └─ ✅ SUCCESS
     └─ Return (channel1, channel2)
     └─ Log "sent ad1 → channel2 OK"
```

**Note: Cooldown is 3 days (pairwise), delay is per-server configurable (default 6h).**

---

## Phase 6: Cleanup & Summary

**Release locks and log results.**

```
After all pairs processed:
  
  ├─ Delete Redis lock
  │  └─ DELETE last_partner_run
  │
  ├─ Release asyncio lock
  │  └─ Exit async with _partner_lock
  │
  └─ Log summary
     ├─ "loop #N fired"
     ├─ Eligible servers: X
     ├─ Pairs matched: Y
     ├─ Sat-out after reroll: Z
     └─ Per-pair success/failure
```

---

## State Flow Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│ LOOP FIRES every 6 hours                                        │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Concurrency Gates                                               │
│  ├─ asyncio.Lock (per-instance)                                │
│  └─ Redis NX "last_partner_run" (cross-instance)               │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 1: index_ads()                                            │
│  ├─ Scan Discord ad_channels for recent messages               │
│  ├─ Run Claude Haiku prescan + AI scan                         │
│  └─ Cache ads in Redis with 30-day TTL                         │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 2: Eligibility Filter                                     │
│  ├─ Check blacklist, config, roles, channels, permissions      │
│  ├─ Validate member/ping role coverage %                       │
│  └─ Check personal delay (last_partnered TTL)                  │
│  Result: available = [(guild_id, member_count), ...]           │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 3: match_servers()                                        │
│  ├─ Generate all pairs, fetch cooldown status                  │
│  ├─ Greedy matching (most-constrained first)                   │
│  └─ Result: pairs=[(a,b),...], sat_out=[c,d,...]             │
└─────────────────────────────────────────────────────────────────┘
                              ↓
        ┌─────────────────────────────────────────┐
        │ sat_out ≥ 2?                           │
        └─────────────────────────────────────────┘
            ↓ YES                      ↓ NO
    ┌──────────────────┐          └──────→ (skip to Phase 5)
    │ Phase 4: Reroll  │
    │ Clear inter-     │
    │ cooldowns, retry │
    └──────────────────┘
            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 5: For each pair, partner(a, b)                           │
│  ├─ Fetch configs, resolve Discord objects                     │
│  ├─ Calculate ping tiers based on member_count ratio           │
│  ├─ Fetch ads from Redis                                       │
│  ├─ SET COOLDOWN FIRST (3 days, pairwise)                      │
│  ├─ Send ad_b + ping_a to server_a (with backoff on 429)      │
│  ├─ Send ad_a + ping_b to server_b (with backoff on 429)      │
│  └─ SET PERSONAL DELAYS (per-server, default 6h)              │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│ Phase 6: Cleanup                                                │
│  ├─ Delete Redis lock                                          │
│  ├─ Release asyncio lock                                       │
│  └─ Next cycle in 6 hours                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Structures

**In-Memory:**
- `available`: List of (guild_id, member_count) tuples
- `neighbors`: Dict[guild_id → Set[eligible_partners]]
- `pairs`: List of (guild_a, guild_b) matched tuples
- `sat_out`: List of guild_ids not matched

**Redis:**
- `ads:{guild_id}`: Cached ad text (no TTL, persistent)
- `{cache_version}:partner_cooldown:{min_id}:{max_id}`: Cooldown flag (TTL: 3d)
- `last_partnered:{guild_id}`: Personal delay marker (TTL: per-config, 1h-7d)
- `last_partner_run`: Distributed lock (TTL: 3h)
- `bot:guild_ids`: Set of all guild IDs
- `bot:guild_info`: Hash of guild metadata
- `whitelisted_links`: Set of links to strip from ads
- `{claude_cache_version}:claude:{ad_hash}`: Claude scan result (TTL: 30d)

**Postgres:**
- `guild_config`: Server setup (channels, roles, delays)
- `blacklists`: Banned servers
- `whitelisted_links`: Whitelisted ad URLs
- `early_access`: Early access guild whitelist

---

## Edge Cases & Error Handling

### Scenario 1: Blacklist Check (Early-cycle)
```
Guild added to blacklist after index_ads() completes.
Result: Guild still indexed and filtered.
Impact: Blacklist is eventually consistent per loop cycle.
```

### Scenario 2: Config Missing During Eligibility
```
Guild has config but deletes a channel during Phase 2.
Result: Guild skipped in Phase 2 (missing object).
Impact: No ad sent, no cooldown set, retries next cycle.
```

### Scenario 3: Redis Slowness
```
Pipeline for sat-out cooldown clear takes >30s.
Result: Stalls entire matching for one loop (6h cycle).
Impact: Servers wait until next cycle.
```

### Scenario 4: Discord Rate Limit (429)
```
Multiple sends trigger rate limit.
Result: Exponential backoff (5s, 10s, 20s per pair).
Impact: Loop cycle slowed but not blocked; pair stalls up to 35s.
```

### Scenario 5: Half-Success Send
```
Server1 receive ad successfully, Server2 send fails.
Result: Both have cooldown set (set BEFORE sends).
Impact: No partial-success state; safe failure.
```

### Scenario 6: Sat-Out Retry Produces No Matches
```
2 servers sat-out, cooldowns cleared, retry match fails.
Result: Cooldowns restored atomically.
Impact: Servers stay blocked for 3 days as intended.
```

### Scenario 7: Cache Version Rotation
```
cache_version in config.yaml changes.
Result: New pairs use new cache_version, old keys orphaned.
Impact: Migration needed to clean up old keys (not implemented).
```

---

## Performance Notes

**Scaling at 10k guilds:**
- Ad indexing: ~15 min (50 API calls/s, 10k messages)
- Eligibility filter: ~30s (config fetches, validation checks)
- Matching: ~1s (pair generation O(n²) but fast)
- Sending: ~5-10 min (1000 pairs × 30-50ms each)
- Total: ~25-30 minutes, fits in 6-hour window ✓

**Bottlenecks:**
- Discord API rate limits on message history (Phase 1)
- Claude API calls for ad scanning (Phase 1, parallel possible)
- Redis pipeline batch writes (Phase 1)
- Sequential pair sending (Phase 5, parallelizable)

---

## Commands

- `/partner status` — Check why your server may be skipped
- `/partner loopinfo` — When's the next run?
- `/partner force <id1> <id2>` — Admin: force a specific pair now
- `/partner loopforce` — Admin: run loop immediately
- `/partner ad <guild_id>` — Admin: view a cached ad

