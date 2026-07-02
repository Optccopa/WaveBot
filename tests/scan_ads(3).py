import json
import re
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = ["qwen3.5:0.8b", "llama3"][1]

SCAN_PROMPT = """You are a rule violations detector for a Minecraft economy Discord server (DonutSMP).

LEGITIMATE -- do NOT flag these:
- Large in-game currency amounts ("200M", "20B") -- normal in-game money
- Giveaways of in-game items
- Selling in-game services (building, digging, regear, skellys, schematics)
- Urgency language ("ending soon", "limited spots")
- Vouch counts as trust signals
- discord.gg invite links
- Voice call gambling between players

VIOLATIONS -- flag these exactly:

INVITE_REWARDS: Promising in-game money or items for inviting people to the server.
IRL_TRADING: Buying or selling in-game money/items for real money (PayPal, gift cards, cash).
EXTERNAL_GAMBLING: Gambling using Discord bots or bot commands.
BOOST_REWARDS: Rewarding Discord server boosts with in-game money or items.
CROSS_SERVER_TRADING: Trading DonutSMP items for items from another server.
HACKS_OR_CHEATS: Hacked clients, macros, scripts, duplication, account sharing, ban evasion.
NON_DISCORD_LINK: Any URL that is not discord.gg or discord.com.

You MUST respond with ONLY valid JSON. No markdown. No explanation. No backticks.
{"sus": false, "confidence": 0.95, "ai_block": ["violation: quoted phrase"]}
ai_block is empty list if nothing found."""

EXPLAIN_PROMPT = """A Discord server advertisement was flagged for rule violations.

Write a single short plain-English sentence explaining why it was flagged, suitable to send as a moderation reason to the user. Be specific about what was found. Do not use bullet points. Do not say "I" or "the system, do not reffer to permissions or staff members approval".

Violations found:
{violations}

Respond with ONLY the explanation sentence, nothing else."""

RULE_PATTERNS = {
    "INVITE_REWARDS": [
        r"\bper invite\b",
        r"\binvite.{0,30}(reward|get|earn|win|receiv)",
        r"\b(earn|get|win|receiv).{0,30}invite",
        r"\d+[mk]?\s*(coins?|mil|million|money)?\s*per invite",
        r"\binvite reward",
        r"\btop inviter",
        r"\binvite\s+\d+\s+(friends?|people|ppl|members?)",
        r"\b(have to|gotta|must)\s+invite",
    ],
    "IRL_TRADING": [
        r"\bgift card",
        r"\birl",
        r"\breal.?money\b",
        r"\birl trad",
        r"\bautobuy\b",
        r"\bauto.?buy\b",
        r"\bbuy.{0,20}(donut|ingame|in.game).{0,20}(money|currency)",
        r"\b\$\d+\b",
        r"\busd\b",
    ],
    "EXTERNAL_GAMBLING": [
        r"\b/gamble\b",
        r"\bgambl.{0,10}bot",
        r"\bbot.{0,10}(coinflip|gambl)",
        r"\bcoinflip bot",
        r"\blucky spin",
        r"\b!gamble\b",
    ],
    "BOOST_REWARDS": [
        r"\bboost.{0,40}(get|earn|win|receiv|reward|point|bonus|extra)",
        r"\b(get|earn|win).{0,20}boost",
        r"\bnitro.{0,20}(get|earn|reward|win)",
        r"\baccepting.{0,10}nitro",
        r"\bboost.{0,20}\d+[mk]\b",
    ],
    "CROSS_SERVER_TRADING": [
        r"\btrade.{0,30}for\s+\w+smp",
        r"\bcross.?server",
        r"\b\w+smp.{0,20}(trade|swap|exchange)",
    ],
    "HACKS_OR_CHEATS": [
        r"\bdup(ed?|ing)\b",
        r"\bxray\b",
        r"\bhacked? client",
        r"\bmacro\b",
        r"\bauto.?click",
        r"\bexploit\b",
        r"\bundetectable\b",
        r"\blog.{0,10}into.{0,10}(your|ur|their) account",
    ],
    "NON_DISCORD_LINK": [
        r"https?://(?!discord\.gg|discord\.com|cdn\.discord)",
    ],
}


def regex_check(ad_text: str) -> list[str]:
    hits = []
    lower = ad_text.lower()
    for rule, patterns in RULE_PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, lower):
                hits.append(f"{rule}: {m.group()}")
    return hits


def generate_explanation(violations: list[str]) -> str:
    prompt = EXPLAIN_PROMPT.format(violations="\n".join(violations))
    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
        },
    )
    return response.json()["response"].strip()


def scan_ads(ad_texts: list[str]):
    for ad in ad_texts:
        regex_hits = regex_check(ad)

        regex_context = ""
        if regex_hits:
            lines = [f"- {h}" for h in regex_hits]
            regex_context = "\nRegex pre-scan found:\n" + "\n".join(lines) + "\n"

        response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": SCAN_PROMPT + regex_context + "\n\nAdvertisement:\n" + ad,
                "stream": False,
                "format": "json",
            },
        )
        raw = response.json()["response"]
        result = json.loads(raw)

        ai_block = [
            v for v in result.get("ai_block", []) if v != "violation: quoted phrase"
        ]

        # Merge regex hits into result, override if model missed
        all_violations = list(set(regex_hits + ai_block))

        if regex_hits and not result.get("sus"):
            result["sus"] = True
            result["confidence"] = max(result.get("confidence", 0.5), 0.85)

        explanation = None
        if all_violations:
            explanation = generate_explanation(all_violations)

        yield (
            {
                "sus": result.get("sus", False),
                "confidence": result.get("confidence", 0.0),
                "regex_block": regex_hits,
                "ai_block": ai_block,
                "explanation": explanation,
            },
            ad[:50],
        )


if __name__ == "__main__":
    ads = [
        "# 🍩 DonutSMP Shop Hub 🍩\n**__Fresh Stock Daily__**\n- Iron / Gold / Redstone\n- Cheap Totems (bulk discounts)\n- Enchanted Gear ⚔️\n- Fast delivery 🚀\n\n> Vouches: 120+\n> Dm me or join: https://discord.gg/fakeshop1",
        "# FREE $$$ FOR INVITES 💸\nInvite 5 ppl = 1M ingame cash\nInvite 10 ppl = FULL NETHERITE SET 🔥\n\nNo scam fr just tryna grow 🙏\nJoin fast: https://discord.gg/invitecash",
        "# __Skyline Builds__ 🏙️\nNeed a base?\nI build:\n- Megabases\n- Vaults\n- Hidden stash spots 👀\n\nPrices negotiable, dm me anytime\n> 50+ satisfied clients",
        "# 💰 SELLING DONUTSMP MONEY IRL 💰\n$5 = 2mil\n$20 = 10mil + bonus items\n\nPaypal / Cashapp only\nFast & safe, done 30+ deals\n\nDm me quick before stock gone",
        "# 🎰 Donut Gamble Bot 🎰\n- Coinflip\n- Slots\n- Jackpot\n\nWin BIG $$$ ingame 💸\nInstant payouts\n\nJoin now: https://discord.gg/gamblebot",
        "# __Miner's Outlet__ ⛏️\nCheap bulk ores:\n- Diamonds 💎\n- Ancient debris\n- Coal (lol)\n\nDiscounts for returning buyers\nFast response!!",
        "# 🚀 BOOST = REWARDS 🚀\nBoost our server = get:\n- 500k ingame\n- Free gear set\n\nLimited time only!!\nhttps://discord.gg/boostreward",
        "# __Donut Builders Guild__ 🏗️\nWe offer:\n- Base building\n- Terraforming 🌲\n- Redstone farms\n\n**100% legit** no grief\nDm for portfolio",
        "# 🧱 DIGGING SERVICE 🧱\nNeed chunk cleared?\nWe mine FAST\n\nPrices:\n- Per chunk or per hour\n\nCrew of 5 active grinders\nDm me asap",
        "# 🔥 OP KITS GIVEAWAY 🔥\nJoin server & react to win\nGiving away FULL god set\n\nEnds tonight\nhttps://discord.gg/giveaway123",
        "# __Cross Server Trades__ 🌐\nTrading DonutSMP items for Hypixel coins\nAlso accepting other servers\n\nTrusted trader, dm offers",
        "# ⚔️ PVP GEAR SHOP ⚔️\n- Maxed swords\n- God armor sets\n- Totem packs\n\nCheap cheap cheap\n\n> 200+ vouches",
        "# 🌍 BASE SELLING 🌍\nSelling hidden bases coords\n- Undetected\n- Fully loaded chests\n\nSerious buyers only",
        "# __Auto Farms & Schematics__ 🤖\n- Sugarcane farms\n- Raid farms\n- Iron farms\n\nInstant download + tutorial\n\nJoin: https://discord.gg/schems",
        "# 💎 Diamond Duping Method 💎\nWorking 100% rn\nSelling method for cheap\n\nDm before patch",
        "# 🛒 __Cactus & Gunpowder Shop__ 🛒\nBest rates rn\n- Bulk deals\n- Fast trades\n\n> always online",
        "# 🧑‍🌾 Farming Service 🧑‍🌾\nI grind for u:\n- crops\n- mobs\n- money\n\nYou chill I work 😎\nDm prices",
        "# 🎁 DAILY REWARDS SERVER 🎁\nJoin for free stuff everyday\nCoins, items, kits\n\nDon’t miss out\nhttps://discord.gg/dailyloot",
        "# __Vault Protection Builds__ 🔐\nHidden vaults, anti-xray tricks\n\nNo one finding ur loot again\n\nDm for custom builds",
        "# 🐍 Hacked Client Configs 🐍\nBest configs for Donut\n- Undetectable\n- OP settings\n\nDm for access",
    ]
    for result, pre in scan_ads(ads):
        print(json.dumps(result, indent=2))
