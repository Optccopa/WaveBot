from discord.ext import tasks, commands
from redis.asyncio import Redis
from anthropic import Anthropic
import re, discord, os, json, hashlib

CACHE_VER_CLAUDE = "v1"

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

VIOLATIONS -- flag these exactly:

INVITE_REWARDS: Promising in-game money or items for inviting people to the server.
IRL_TRADING: Buying or selling in-game money/items for real money (PayPal, gift cards, cash).
EXTERNAL_GAMBLING: Gambling using Discord bots or bot commands.
BOOST_REWARDS: Rewarding Discord server boosts with in-game money or items.
CROSS_SERVER_TRADING: Trading DonutSMP items for items from another server.
HACKS_OR_CHEATS: Hacked clients, macros, scripts, duplication, account sharing, ban evasion.
NON_DISCORD_LINK: Any URL that is not discord.gg or discord.com.

Respond with a single raw JSON object using this exact schema:
{
    "sus": bool, -- True if ANY violation was found, False if clean
    "confidence": float, -- 0.0 to 1.0, how confident you are in the sus verdict
    "ai_hits": [ -- violations YOU found that regex did not catch, empty list if none {"violation": "VIOLATION_NAME", "phrase": "exact phrase from the ad that triggered it"}],
    "regex_hits": [], -- leave as empty list, this is filled in by the system
    "user_reason": string -- if sus=true, a short friendly message to show the user explaining what they need to fix WITHOUT mentioning regex, AI, or detection methods. if sus=false, set to null. Example: "Your ad appears to offer rewards for inviting members, which isn't allowed." NOT: "Regex pattern INVITE_REWARDS matched '5M / inv' in your message."
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
        r"\birl\b",
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

LINK_REGEX = re.compile(r"https?://\S+")

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.AutoShardedBot = bot
        self.redis: Redis = bot.redis
        self.client: Anthropic = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    
    def scan_ad(self, ad: str) -> dict:
        hits = []
        lower = ad.lower()
        for rule, patterns in RULE_PATTERNS.items():
            for pat in patterns:
                for m in re.finditer(pat, lower):
                    hits.append(f"{rule}: {m.group()}")

        regex_hits = list(set(hits))

        if regex_hits:
            return {
                "sus": True,
                "confidence": 0.95,
                "ai_hits": [],
                "regex_hits": regex_hits,
                "user_reason": "Your ad was flagged during the regex prescan"
            }

        message = self.client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            temperature=0.1,
            system=[{
                "type": "text",
                "text": SCAN_PROMPT,
                "cache_control": {"type": "ephemeral"}
            }],
            messages=[
                {"role": "user", "content": f"Advertisement:\n{ad}"},
                {"role": "assistant", "content": "{"},
            ],
        )
        raw = "{" + message.content[0].text.strip()
        result = json.loads(raw)

        return result

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ad_loop.is_running():
            self.ad_loop.start()

    @tasks.loop(seconds=10800)  # 3 hours
    async def ad_loop(self):
        await self.index_ads()

    async def index_ads(self):
        missingChannelEmbed = discord.Embed(
            title="Ad channel missing",
            description="Use `/config set` to set one",
            color=discord.Color.dark_red()
        )
        missingAdEmbed = discord.Embed(
            title="Ad message missing",
            description="Your ad message was not found in the recent 10 messages in the channel",
            color=discord.Color.dark_red()
        )
        async with self.redis.pipeline() as pipeline:
            for guild in self.bot.guilds:
                guild: discord.Guild
                config = await self.bot.config.get(guild.id)
                if not config:
                    continue

                ad_channel = guild.get_channel(config.get("ad_channel"))
                log_channel = guild.get_channel(config.get("log_channel"))

                if not ad_channel:
                    if log_channel:
                        await log_channel.send(embed=missingChannelEmbed)
                    continue

                ad_message = None
                async for message in ad_channel.history(limit=10):
                    if LINK_REGEX.search(message.content):
                        ad_message = message.content
                        ad_hash = hashlib.md5(ad_message.encode()).hexdigest()[:12]

                        cached = await self.redis.get(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}")
                        if not cached:
                            response = json.dumps(await self.bot.loop.run_in_executor(None, self.scan_ad, ad_message), indent=2)
                            await self.redis.set(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}", response)
                        else:
                            response = cached
                        
                        print(response)

                        break

                if ad_message:
                    await pipeline.set(f"ads:{guild.id}", ad_message)
                else:
                    if log_channel:
                        await log_channel.send(embed=missingAdEmbed)

            await pipeline.execute() 

    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()
        
    async def cog_load(self):
        if self.bot.is_ready() and not self.ad_loop.is_running():
            self.ad_loop.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))