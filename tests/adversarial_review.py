"""Adversarial review tests for match_servers / get_req."""

import random
import json

ALL_PINGS = ["none", "partner", "here", "partnerhere", "member"]


def get_req(count_a: int, count_b: int) -> dict:
    if count_a >= count_b:
        host, guest = count_a, count_b
        a_is_host = True
    else:
        host, guest = count_b, count_a
        a_is_host = False
    REF = 2300
    scale = host / REF
    tiers = [
        (round(400 * scale), "none"),
        (round(800 * scale), "partner"),
        (round(1700 * scale), "here"),
        (round(2000 * scale), "partnerhere"),
        (float("inf"), "member"),
    ]
    ping_a, ping_b = "none", "none"
    for ceiling, host_ping in tiers:
        if guest <= ceiling:
            if a_is_host:
                ping_a, ping_b = host_ping, "member"
            else:
                ping_a, ping_b = "member", host_ping
            break
    return {
        "server_a": ping_a,
        "server_b": ping_b,
        "host": "server_a" if a_is_host else "server_b",
    }


def test_pingkey_mapping():
    # match_servers passes get_req(member_counts[a], member_counts[b]) where a<b by ID.
    # If guild a (lower ID) has more members, a is host. r['server_a'] should be host ping.
    r = get_req(2000, 500)
    assert r["server_a"] == "partner" and r["server_b"] == "member"
    r = get_req(500, 2000)
    assert r["server_a"] == "member" and r["server_b"] == "partner"
    # The mapping is correct: first arg <-> server_a, second arg <-> server_b.


def test_equal_counts_asymmetric():
    # count_a == count_b -> a_is_host=True, host gets host_ping, guest gets 'member'
    # For two 1000-member servers: scale=1000/2300, tiers cap at 870 < 1000, so host_ping='member'
    # Both end up 'member' -- fine
    # But for two 500-member servers: scale=500/2300=0.217
    #   tiers: round(87)=87, round(174)=174, round(370)=370, round(435)=435, inf
    #   guest=500 > 435 -> host_ping='member'. Both 'member'.
    # For two 300-member servers: scale=0.130
    #   tiers: 52, 104, 222, 261, inf. guest=300 > 261 -> 'member'.
    # PROBLEM: When two servers are exactly equal size, by definition guest=host,
    # and guest will always exceed every non-inf tier ceiling because every ceiling
    # is < host. So equal-size pairs ALWAYS get ('member','member'). Likely fine.

    # But the asymmetry for near-equal pairs: 1000 vs 999
    r = get_req(1000, 999)
    print("1000 vs 999:", r)
    r = get_req(999, 1000)
    print("999 vs 1000:", r)


def test_tier_boundary_rounding():
    # round() uses banker's rounding in Python 3. round(0.5)=0, round(1.5)=2.
    # Verify tier ceilings are monotonic increasing for all reasonable host sizes.
    bad = []
    for host in range(0, 100000, 7):
        scale = host / 2300
        t = [
            round(400 * scale),
            round(800 * scale),
            round(1700 * scale),
            round(2000 * scale),
        ]
        for i in range(len(t) - 1):
            if t[i] > t[i + 1]:
                bad.append((host, t))
                break
    print("Non-monotonic tier hosts:", bad[:5], "total:", len(bad))


def test_zero_members():
    # host=0 -> scale=0 -> all tier ceilings = 0
    # guest=0 <= 0 -> first tier matches, host_ping='none'
    r = get_req(0, 0)
    print("0,0:", r)
    # Guild a=0, b=100: a_is_host=False (0 < 100), host=100, guest=0
    # scale=100/2300=0.0435; ceilings: 17, 35, 74, 87, inf
    # guest=0 <= 17 -> 'none'. b gets 'none', a gets 'member'.
    r = get_req(0, 100)
    print("0,100:", r)


def test_negative_or_none():
    # If a guild has member_count=None, the comparison crashes on Python 3.
    try:
        get_req(None, 100)
        print("None,100 OK")
    except TypeError as e:
        print("None,100 raises:", e)
    # Negative
    print("-1, 100:", get_req(-1, 100))


# ============ match_servers logic checks ============


def simulate_match(guilds, premium_data=None, cooldown_pairs=None, seed=0):
    """Simulate the matching logic without redis/db."""
    random.seed(seed)
    premium_data = premium_data or {}
    cooldown_pairs = set(cooldown_pairs or [])

    member_counts = {gid: mc for gid, mc in guilds}
    pool = list(member_counts)
    random.shuffle(pool)

    if len(pool) < 2:
        return [], pool

    all_pairs = [
        (min(a, b), max(a, b)) for i, a in enumerate(pool) for b in pool[i + 1 :]
    ]
    on_cooldown = {p for p in all_pairs if p in cooldown_pairs}

    prem_configs = premium_data

    neighbors = {s: set() for s in pool}
    for a, b in all_pairs:
        if (a, b) in on_cooldown:
            continue
        if a in prem_configs or b in prem_configs:
            r = get_req(member_counts[a], member_counts[b])
            ping_blocked = False
            for gid, ping_key in ((a, "server_a"), (b, "server_b")):
                if gid in prem_configs:
                    allowed = prem_configs[gid].get("available_pings") or ALL_PINGS
                    if r[ping_key] not in allowed:
                        ping_blocked = True
                        break
            if ping_blocked:
                continue
        neighbors[a].add(b)
        neighbors[b].add(a)

    order = sorted(pool, key=lambda x: len(neighbors[x]))
    matched = set()
    pairs = []
    for server in order:
        if server in matched:
            continue
        available = [p for p in neighbors[server] if p not in matched]
        if not available:
            continue
        partner = min(available, key=lambda x: len(neighbors[x] - matched))
        pairs.append((server, partner))
        matched.add(server)
        matched.add(partner)

    sat_out = [s for s in pool if s not in matched]
    return pairs, sat_out


def test_two_guilds():
    p, s = simulate_match([(100, 500), (200, 600)])
    print("2 guilds:", p, s)


def test_three_guilds():
    p, s = simulate_match([(100, 500), (200, 600), (300, 700)])
    print("3 guilds:", p, s)


def test_one_guild():
    p, s = simulate_match([(100, 500)])
    print("1 guild:", p, s)


def test_zero_guilds():
    p, s = simulate_match([])
    print("0 guilds:", p, s)


def test_all_on_cooldown():
    g = [(100, 500), (200, 600), (300, 700)]
    cd = [(100, 200), (100, 300), (200, 300)]
    p, s = simulate_match(g, cooldown_pairs=cd)
    print("all cooldown:", p, s)


def test_premium_pingblock_isolated():
    # Premium guild only allows 'none' ping. Pair with non-premium where required ping is 'partner'.
    # 100 (premium, only 'none') vs 200 (non-premium, 2000 members)
    # get_req(member_counts[100]=500, member_counts[200]=2000): a=100 <count 500, b=200 count 2000
    # b is host -> server_b=host_ping, server_a='member'. host=2000,guest=500,scale=0.87
    # ceilings: 348, 696, 1478, 1739, inf. guest=500 <= 696 -> 'partner'
    # So r = {server_a:'member', server_b:'partner'}
    # Premium guild 100 has ping_key='server_a' -> r['server_a']='member'. 'member' in ['none']? No -> blocked. Correct.
    p, s = simulate_match(
        [(100, 500), (200, 2000)],
        premium_data={100: {"available_pings": ["none"]}},
    )
    print("premium block test:", p, s)


def test_premium_empty_list_falsy():
    # available_pings = [] is falsy -> falls back to ALL_PINGS. BUG? Probably intentional
    # but means "I want no pings" is impossible to configure with empty list.
    p, s = simulate_match(
        [(100, 500), (200, 2000)],
        premium_data={100: {"available_pings": []}},
    )
    print("empty pings list (treated as ALL):", p, s)


def test_pair_ordering_consistency():
    # all_pairs uses (min(a,b), max(a,b)) by ID. neighbors[a].add(b) uses pair tuple's a,b
    # so neighbors map uses ID-ordered keys. OK.
    # But the get_req call passes member_counts[a], member_counts[b] where a<b by ID.
    # server_a corresponds to lower-ID guild, server_b to higher-ID. Consistent.
    pass


def test_greedy_optimality():
    # Greedy may leave servers unmatched even when perfect matching exists.
    # Construct a case: A-B, A-C, B-D edges. Optimal: A-C, B-D (or A-B leaving C,D unmatched)
    # Set up so cooldowns/premium constraints create exactly that graph.
    # 4 guilds: 1,2,3,4. Edges allowed: (1,2),(1,3),(2,4). Forbid (1,4),(2,3),(3,4).
    g = [(1, 500), (2, 500), (3, 500), (4, 500)]
    cd = [(1, 4), (2, 3), (3, 4)]
    p, s = simulate_match(g, cooldown_pairs=cd, seed=1)
    print("greedy 4-node test:", p, s, "(optimal: 2 pairs, e.g., (1,3),(2,4))")


def test_shuffle_determinism():
    # Same input, different seeds -> different results possible. That's by design.
    for seed in range(3):
        p, s = simulate_match(
            [(1, 100), (2, 200), (3, 300), (4, 400), (5, 500)], seed=seed
        )
        print(f"seed {seed}: pairs={p} satout={s}")


def test_sat_out_order():
    # sat_out iterates pool (shuffled). Order is non-deterministic. Caller beware.
    p, s = simulate_match([(1, 100), (2, 200), (3, 300)], seed=0)
    print("sat_out (shuffled order):", s)


def test_duplicate_guild_ids():
    # If guilds list has duplicates, member_counts dict collapses them silently.
    g = [(1, 100), (1, 200), (2, 300)]
    p, s = simulate_match(g)
    print("dup ids (silently collapsed):", p, s)


if __name__ == "__main__":
    print("--- get_req ---")
    test_pingkey_mapping()
    test_equal_counts_asymmetric()
    test_tier_boundary_rounding()
    test_zero_members()
    test_negative_or_none()
    print("--- match_servers ---")
    test_two_guilds()
    test_three_guilds()
    test_one_guild()
    test_zero_guilds()
    test_all_on_cooldown()
    test_premium_pingblock_isolated()
    test_premium_empty_list_falsy()
    test_greedy_optimality()
    test_shuffle_determinism()
    test_sat_out_order()
    test_duplicate_guild_ids()
