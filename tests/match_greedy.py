import random, asyncio, time

servers = list(range(31))

random.seed(42)
_hot = set(random.sample(servers, int(len(servers) * 0.3)))
_cooldown_pairs: set[tuple[int, int]] = set()
for _a in _hot:
    for _b in servers:
        if _a != _b:
            _cooldown_pairs.add((min(_a, _b), max(_a, _b)))


class Cog:
    def __init__(self):
        pass

    async def match(self, players: list[int]) -> tuple[list[tuple[int, int]], list[int]]:
        pool = players[:]
        random.shuffle(pool)

        if len(pool) < 2:
            return [], pool

        all_pairs = [(min(a, b), max(a, b)) for i, a in enumerate(pool) for b in pool[i + 1:]]

        # Simulate pipeline (in prod this is one Redis round-trip)
        on_cooldown = {pair for pair in all_pairs if pair in _cooldown_pairs}

        neighbors: dict[int, set[int]] = {s: set() for s in pool}
        for a, b in all_pairs:
            if (a, b) not in on_cooldown:
                neighbors[a].add(b)
                neighbors[b].add(a)

        order = sorted(pool, key=lambda x: len(neighbors[x]))
        matched: set[int] = set()
        pairs: list[tuple[int, int]] = []

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


async def run():
    total_pairs = 0
    total_sat = 0
    runs = 30

    start = time.perf_counter()
    for i in range(runs):
        pairs, sat_out = await Cog().match(servers)
        total_pairs += len(pairs)
        total_sat += len(sat_out)
        print(f"[{i:02d}] pairs={len(pairs)} sat_out={len(sat_out)} | {pairs}")
        if sat_out:
            print(f"     sat: {sat_out}")

    elapsed = time.perf_counter() - start
    print(f"\n--- {runs} runs in {elapsed*1000:.2f}ms ---")
    print(f"avg pairs:   {total_pairs/runs:.1f}")
    print(f"avg sat_out: {total_sat/runs:.1f}")
    print(f"avg ms/run:  {elapsed/runs*1000:.3f}ms")

asyncio.run(run())
