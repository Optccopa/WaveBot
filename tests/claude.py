import json
import anthropic
import re
from src.prompts import *

API_KEY = "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"

client = anthropic.Anthropic(api_key=API_KEY)

def scan_ad(ad: str) -> dict:
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

    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
        system=SCAN_PROMPT,
        messages=[
            {"role": "user", "content": f"Advertisement:\n{ad}"},
            {"role": "assistant", "content": "{"},
        ],
    )
    raw = "{" + message.content[0].text.strip()
    result = json.loads(raw)

    return result

if __name__ == "__main__":
    result = scan_ad("""
# Money Shop
Selling donut money for cheap
Rates in dm
Serious buyers only
discord.gg/shopsusa
                     """)
    print(json.dumps(result, indent=4))