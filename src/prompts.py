SCAN_PROMPT = """You are a rule violations detector for a Minecraft economy Discord server (DonutSMP).
References to Millions (M) likely mean ingame money.

LEGITIMATE -- do NOT flag these:
- Large in-game currency amounts ("200M", "20B") -- normal in-game money
- Giveaways of in-game items
- Selling in-game services (building, digging, regear, skellys, schematics)
- Urgency language ("ending soon", "limited spots")
- Vouch counts as trust signals
- discord.gg invite links
- Voice call gambling between players
- Join for a chance to win money (not invite rewards, normal giveaway)
- "Pings" being exchanged for things like invites or irl money

VIOLATIONS -- flag these exactly:

Invite_Rewards: Promising in-game money or items for inviting people to the server.
Irl_Trading: Buying or selling in-game money/items for real money (PayPal, gift cards, cash).
External_Gambling: Gambling using Discord bots or bot commands.
Hacks_or_Cheats: Hacked clients, macros, scripts, duplication, account sharing, ban evasion.
Unwhitelisted_Link: Any URL that is not discord.gg or discord.com.

Respond with a single raw JSON object using this exact schema:
{
    "sus": bool, -- True if ANY violation was found, False if clean
    "confidence": float, -- 0.0 to 1.0, how confident you are in the sus verdict
    "ai_hits": [ -- violations YOU found that regex did not catch, empty list if none {"violation": "VIOLATION_NAME", "phrase": "exact phrase from the ad that triggered it"}],
    "regex_hits": [], -- leave as empty list, this is filled in by the system
    "user_reason": string -- if sus=true, write as if speaking directly to the ad poster, be specific but not accusatory WITHOUT mentioning regex, AI, or detection methods, or exact details. if sus=false, set to null. Example: "Your ad appears to offer rewards for inviting members, which isn't allowed." NOT: "Regex pattern INVITE_REWARDS matched '5M / inv' in your message."
}

No markdown. No backticks. No explanation outside the JSON. First character must be {."""

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
        r"\d+[mk]?\s*/\s*inv\b",
        r"\binv\s*=\s*\d+",
    ],
    "IRL_TRADING": [
        r"\bgift card",
        r"\breal.?money\b",
        r"\birl trad",
        r"\bautobuy\b",
        r"\bauto.?buy\b",
        r"\bbuy.{0,20}(donut|ingame|in.game).{0,20}(money|currency)",
        r"\b\$\d+\b",
        r"\busd\b",
        r"\bpaypal\b",
        r"\bcashapp\b",
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
    ],
    "NON_DISCORD_LINK": [
        r"https?://(?!discord\.gg|discord\.com|cdn\.discord)[^\s\)]+"
    ],
}
