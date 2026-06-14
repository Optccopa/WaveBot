# Caching Reference

## Pipelines

Batch multiple Redis commands into one round-trip. Use for independent reads:

```python
async with self.redis.pipeline(transaction=False) as pipe:
    pipe.get(f"config:{guild_id}")
    pipe.get(f"premium:{guild_id}")
    pipe.sismember("bot:guild_ids", str(guild_id))
    config_raw, premium_raw, is_member = await pipe.execute()
```

`transaction=False` skips MULTI/EXEC overhead — use it unless you need atomicity.

With atomicity (all-or-nothing):

```python
async with self.redis.pipeline(transaction=True) as pipe:
    pipe.set(key1, val1)
    pipe.set(key2, val2)
    await pipe.execute()
```

## Sorted Sets for Time Windows

Track events in a sliding window (e.g., partners in last 24h):

```python
import time

ts = time.time()
cutoff = ts - 86400  # 24 hours ago

# Record an event
await self.redis.zadd("stats:partners:24h", {f"{ts}:{unique_id}": ts})

# Evict expired entries, then count
await self.redis.zremrangebyscore("stats:partners:24h", 0, cutoff)
count = await self.redis.zcard("stats:partners:24h")
```

Member string must be unique (append a unique ID if the score alone isn't unique).

## Distributed Lock (Stampede Prevention)

Prevent multiple instances or concurrent callers from executing the same work:

```python
acquired = await self.redis.set("lock:partner_loop", "1", nx=True, ex=55)
if not acquired:
    return  # another instance holds the lock
try:
    await do_expensive_work()
finally:
    await self.redis.delete("lock:partner_loop")
```

TTL (`ex=`) must be shorter than the loop interval so a crashed instance doesn't block forever. A 60s loop uses a 55s TTL.

`nx=True` makes the SET conditional — only sets if key doesn't exist. Returns `True` on success, `None` on failure.

## Negative Caching

Cache misses explicitly so repeated lookups of non-existent rows skip the DB:

```python
cached = await self.redis.get(f"config:{guild_id}")
if cached == "0":
    return None  # known miss, don't hit DB
if cached:
    return json.loads(cached)

row = await conn.fetchrow("SELECT ...")
if row is None:
    await self.redis.set(f"config:{guild_id}", "0", ex=86400)  # 1-day negative TTL
    return None

await self.redis.set(f"config:{guild_id}", json.dumps(dict(row)), ex=2592000)
return dict(row)
```

## Exists-Only Keys

Some keys are used purely for their existence (no value needed):

```python
# Set (no value, just presence)
await self.redis.set(f"partner_cooldown:{a}:{b}", "1", ex=172800)

# Check
exists = await self.redis.exists(f"partner_cooldown:{a}:{b}")  # 0 or 1
```

Same pattern for rate-limit warnings (`warn:{key}:{guild_id}`).

## TTL Reference

| Purpose | TTL |
|---------|-----|
| Guild config / premium | 2592000s (30 days) |
| Negative cache (missing rows) | 86400s (1 day) |
| Claude scan result | 2592000s (30 days) |
| Partner cooldown between two guilds | 172800s (2 days) |
| Last-partner timestamp | 604800s (7 days) |
| Cached invite URL | 21600s (6 hours) |
| Rate-limit warning | 21600s (6 hours) |
| Distributed loop lock | 55s |

Always read TTLs from `yaml_config` where they're defined there — don't hardcode in cog logic.

## Cache Invalidation

After any write that changes cached data, delete the key:

```python
await self.redis.delete(f"config:{guild_id}")
```

`ConfigManager.set()` and `PremiumManager.set()` do this internally. For keys you manage directly, invalidate immediately after the DB write completes.

## Cache Version Prefix

Caches tied to prompt/logic versions use a version prefix:

```python
cache_ver = self.yaml_config['cache']['cache_version']      # "v1"
claude_ver = self.yaml_config['ai']['claude_cache_version'] # separate key
key = f"{claude_ver}:claude:{ad_hash}"
```

Bumping the version in `config.yaml` effectively invalidates all keys with that prefix without needing to delete them.
