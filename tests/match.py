import random, asyncio

servers = list(range(31))

random.seed(42)
_hot = set(random.sample(servers, int(len(servers) * 0.9)))
_cooldown_pairs: set[tuple[int, int]] = set()
for _a in _hot:
    for _b in servers:
        if _a != _b:
            _cooldown_pairs.add((min(_a, _b), max(_a, _b)))

class Cog:
    def __init__(self):
        pass

    async def has_cooldown(self, a, b):
        return (min(a, b), max(a, b)) in _cooldown_pairs

    async def match(self, players: list[int]) -> tuple[list[tuple[int, int]], list[int]]:
        shuffled = players[:]
        random.shuffle(shuffled)

        cooldowns = set()
        for i, a in enumerate(shuffled):
            for b in shuffled[i + 1:]:
                if await self.has_cooldown(a, b):
                    cooldowns.add((min(a, b), max(a, b)))

        def backtrack(remaining: list[int]) -> list[tuple[int, int]]:
            if len(remaining) < 2:
                return []

            first = remaining[0]
            rest = remaining[1:]
            best = []

            for i, candidate in enumerate(rest):
                key = (min(first, candidate), max(first, candidate))
                if key not in cooldowns:
                    result = [(first, candidate)] + backtrack(rest[:i] + rest[i + 1:])
                    if len(result) > len(best):
                        best = result
                        if len(best) == len(remaining) // 2:
                            return best

            skipped = backtrack(rest)
            if len(skipped) > len(best):
                best = skipped

            return best

        pairs = backtrack(shuffled)
        paired = {p for pair in pairs for p in pair}
        sat_out = [p for p in shuffled if p not in paired]
        return pairs, sat_out

for i in range(30):
    pairs, sat_out = asyncio.run(Cog().match(servers))
    print(pairs, f"\n{sat_out}")
