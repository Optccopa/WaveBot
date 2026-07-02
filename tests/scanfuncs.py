import json
import re
import requests

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3"

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
{"sus": false, "confidence": 0.95, "ai_block": ["VIOLATION_TYPE: quoted phrase"]}
ai_block is empty list if nothing found."""

EXPLAIN_PROMPT = """A Discord server advertisement was flagged for rule violations:
{violations}

Write one short sentence explaining what was found. Only reference what is listed above. Do not add details not in the list. Do not mention Discord rules or guidelines by name.

Respond with ONLY the sentence."""

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
        r"\bpaypal\b",
        r"\bcashapp\b",
        r"\bvenmo\b",
        r"\bgift card",
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
        r"\bfyresmp\b",
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
        r"\bundetected\b",
        r"\blog.{0,10}into.{0,10}(your|ur|their) account",
    ],
    "NON_DISCORD_LINK": [
        r"https?://(?!discord\.gg|discord\.com|cdn\.discord)",
    ],
}


def scan_regex(ad_text: str) -> list[str]:
    """Regex-only scan. Returns list of matched rule: phrase strings."""
    hits = []
    lower = ad_text.lower()
    for rule, patterns in RULE_PATTERNS.items():
        for pat in patterns:
            for m in re.finditer(pat, lower):
                hits.append(f"{rule}: {m.group()}")
    return hits


def scan_ai(ad_text: str) -> dict:
    """Full scan — regex + AI + explanation. Returns result dict."""
    regex_hits = scan_regex(ad_text)

    regex_context = ""
    if regex_hits:
        lines = [f"- {h}" for h in regex_hits]
        regex_context = "\nRegex pre-scan found:\n" + "\n".join(lines) + "\n"

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": MODEL,
            "prompt": SCAN_PROMPT + regex_context + "\n\nAdvertisement:\n" + ad_text,
            "stream": False,
            "format": "json",
        },
    )
    raw = response.json()["response"]
    result = json.loads(raw)

    ai_block = [
        v for v in result.get("ai_block", []) if v != "violation: quoted phrase"
    ]

    all_violations = list(set(regex_hits + ai_block))

    sus = result.get("sus", False)
    confidence = result.get("confidence", 0.0)

    if regex_hits and not sus:
        sus = True
        confidence = max(confidence, 0.85)

    explanation = None
    if all_violations:
        exp_response = requests.post(
            OLLAMA_URL,
            json={
                "model": MODEL,
                "prompt": EXPLAIN_PROMPT.format(violations="\n".join(all_violations)),
                "stream": False,
            },
        )
        explanation = exp_response.json()["response"].strip()

    return {
        "sus": sus,
        "confidence": confidence,
        "regex_block": regex_hits,
        "ai_block": ai_block,
        "explanation": explanation,
    }


if __name__ == "__main__":
    ads = [
        "selling emeralds 500k stack for $12 paypal.... need real money quick lmk",
        "# Copa's Market\n- Best prices on skellys\n- 300+ vouches\nhttps://discord.gg/abc123",
        "FREE COINS!! invite 5 friends and get 50M each\nhttps://discord.gg/xyz",
    ]
    for ad in ads:
        print("--- REGEX ONLY ---")
        print(scan_regex(ad))
        print("--- FULL SCAN ---")
        print(json.dumps(scan_ai(ad), indent=2))
        print()
