import random, asyncio

servers = []
for i in range(31):
    servers.append(i)

# Make sure its not uneven here
class Cog:
    def __init__(self):
        pass

    async def has_cooldown(self, b, c):
        return random.randint(1,10) == 5
    
    async def match(self, players: list[int]) -> list[tuple[int, int]]:
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

            # try pairing first with each candidate, keep the best result
            for i, candidate in enumerate(rest):
                key = (min(first, candidate), max(first, candidate))
                if key not in cooldowns:
                    result = [(first, candidate)] + backtrack(rest[:i] + rest[i + 1:])
                    if len(result) > len(best):
                        best = result
                        if len(best) == len(remaining) // 2:
                            return best  # optimal, no need to keep searching

            # try skipping first entirely
            skipped = backtrack(rest)
            if len(skipped) > len(best):
                best = skipped

            return best

        return backtrack(shuffled)

for i in range(30):
    print(asyncio.run(Cog().match(servers)))