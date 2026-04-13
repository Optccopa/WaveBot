from discord.ext import tasks, commands
from redis.asyncio import Redis
from anthropic import AsyncAnthropic
from src.prompts import SCAN_PROMPT, RULE_PATTERNS
import re, discord, os, json, hashlib, asyncio

CACHE_VER_CLAUDE = "v2"
LINK_REGEX = re.compile(r"https?://\S+")
_PIPELINE_BATCH = 500

class AdLooper(commands.Cog):
    def __init__(self, bot):
        self.bot: commands.AutoShardedBot = bot
        self.redis: Redis = bot.redis
        self.client: AsyncAnthropic = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    async def scan_ad(self, ad: str) -> dict:
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

        message = await self.client.messages.create(
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
        try:
            raw = "{" + message.content[0].text.strip()
            result = json.loads(raw)
        except json.JSONDecodeError:
            print("Failed to parse claude haiku response for ad: %.100s", ad)
            result = {"sus": True, "confidence": 0.5, "ai_hits": [], "regex_hits": [], "user_reason": "Your ad could not be automatically verified. Please review the server rules and resubmit."}

        return result

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.ad_loop.is_running():
            self.ad_loop.start()

    @tasks.loop(seconds=10800)  # 3 hours
    async def ad_loop(self):
        await self.index_ads()

    async def index_ads(self):
        whitelisted = await self.redis.smembers("whitelisted_links")

        missing_channel_embed = discord.Embed(
            title="Ad channel missing",
            description="Use `/config set` to set one",
            color=discord.Color.dark_red()
        )
        missing_ad_embed = discord.Embed(
            title="Ad message missing",
            description="Your ad message was not found in the recent 10 messages in the channel",
            color=discord.Color.dark_red()
        )

        pending = []

        for guild in self.bot.guilds:
            config = await self.bot.config.get(guild.id)
            if not config:
                continue

            ad_channel = guild.get_channel(config.get("ad_channel"))
            log_channel = guild.get_channel(config.get("log_channel"))

            if not ad_channel:
                if log_channel:
                    await log_channel.send(embed=missing_channel_embed)
                continue

            ad_message = None
            async for message in ad_channel.history(limit=10):
                if LINK_REGEX.search(message.content):
                    ad_message = message.content
                    for link in whitelisted:
                        ad_message = ad_message.replace(link, "")
                    ad_hash = hashlib.sha256(ad_message.encode()).hexdigest()[:12]

                    cached = await self.redis.get(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}")
                    if not cached:
                        try:
                            scan_result = await asyncio.wait_for(self.scan_ad(ad_message), timeout=30.0)
                        except asyncio.TimeoutError:
                            scan_result = {"sus": False, "confidence": .5, "ai_hits": [], "regex_hits": [], "user_reason": "Timed out"}
                        response = json.dumps(scan_result, indent=2)
                        await self.redis.set(f"{CACHE_VER_CLAUDE}:claude:{ad_hash}", response)
                    else:
                        response = cached

                    print("[cache_ads] guild %s scan result: %s", guild.id, response)
                    break

            if ad_message:
                pending.append((f"ads:{guild.id}", ad_message))
            else:
                if log_channel:
                    await log_channel.send(embed=missing_ad_embed)

        for i in range(0, max(len(pending), 1), _PIPELINE_BATCH):
            chunk = pending[i:i + _PIPELINE_BATCH]
            if not chunk:
                break
            async with self.redis.pipeline() as pipe:
                for key, value in chunk:
                    pipe.set(key, value)
                await pipe.execute()

    @ad_loop.before_loop
    async def before_ad_loop(self):
        await self.bot.wait_until_ready()

    async def cog_load(self):
        if self.bot.is_ready() and not self.ad_loop.is_running():
            self.ad_loop.start()

async def setup(bot: commands.Bot):
    await bot.add_cog(AdLooper(bot))
