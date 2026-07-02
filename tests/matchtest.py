final = [
    (1, 363),
    (2, 8941),
    (3, 9020),
    (4, 1015),
    (5, 741),
    (6, 2423),
    (7, 7147),
    (8, 5847),
    (9, 6506),
    (10, 8955),
    (11, 6861),
    (12, 8174),
    (13, 6635),
    (14, 629),
    (15, 3875),
    (16, 6495),
    (17, 6898),
    (18, 4831),
    (19, 7231),
    (20, 1503),
]


def match_servers(
    guilds: list[tuple[int, int]], candidates: int = 3
) -> list[tuple[int, int]]:
    sorted_guilds = sorted(guilds, key=lambda g: g[1])
    pairs = []
    used = set()

    for i, (id_a, _) in enumerate(sorted_guilds):
        if id_a in used:
            continue
        # Look at next `candidates` servers closest in size
        pool = [
            (id_b, mc)
            for id_b, mc in sorted_guilds[i + 1 : i + 1 + candidates]
            if id_b not in used
        ]
        if not pool:
            continue
        id_b = random.choice(pool)[0]
        pairs.append((id_a, id_b))
        used.update([id_a, id_b])

    return pairs


import random


def test(n: int = 20, min_members: int = 50, max_members: int = 10000):
    servers = [(i, random.randint(min_members, max_members)) for i in range(1, n + 1)]
    sizes = dict(servers)
    pairs = match_servers(servers)

    print(f"{'ID A':<6} {'Size A':>8}    {'ID B':<6} {'Size B':>8}    {'Diff':>8}")
    print("-" * 50)
    for a, b in pairs:
        diff = abs(sizes[a] - sizes[b])
        print(f"{a:<6} {sizes[a]:>8}    {b:<6} {sizes[b]:>8}    {diff:>8}")
    print(
        f"\nAvg diff: {sum(abs(sizes[a] - sizes[b]) for a, b in pairs) / len(pairs):.0f}"
    )


test()
