import os
import requests
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from google import genai


# ============================================================
# CONFIG
# ============================================================

MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not MARKETAUX_API_KEY:
    raise RuntimeError("MARKETAUX_API_KEY secret is missing")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY secret is missing")


# ============================================================
# US MARKET TIME
# ============================================================

ET = ZoneInfo("America/New_York")


def get_market_slot():

    now_et = datetime.now(ET)

    hour = now_et.hour
    minute = now_et.minute

    # --------------------------------------------------------
    # PRE-MARKET
    # 8:30 AM ET
    # --------------------------------------------------------

    if hour == 8 and minute == 30:
        return "PRE_MARKET"

    # --------------------------------------------------------
    # MARKET OPEN
    # 10:00 AM ET
    # --------------------------------------------------------

    if hour == 10 and minute == 0:
        return "MARKET_OPEN"

    # --------------------------------------------------------
    # MID-MARKET
    # 1:00 PM ET
    # --------------------------------------------------------

    if hour == 13 and minute == 0:
        return "MID_MARKET"

    # --------------------------------------------------------
    # MARKET CLOSE
    # 4:15 PM ET
    # --------------------------------------------------------

    if hour == 16 and minute == 15:
        return "MARKET_CLOSE"

    return None


# ============================================================
# GET US MARKET NEWS
# ============================================================

def get_market_news():

    url = "https://api.marketaux.com/v1/news/all"

    params = {
        "api_token": MARKETAUX_API_KEY,
        "countries": "us",
        "language": "en",
        "filter_entities": "true",
        "must_have_entities": "true",
        "limit": 10,
    }

    print("Requesting Marketaux news...")

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    articles = data.get("data", [])

    if not articles:
        raise RuntimeError(
            "No US market news returned by Marketaux"
        )

    return articles


# ============================================================
# PREPARE NEWS FOR AI
# ============================================================

def prepare_news(articles):

    news_text = []

    for index, article in enumerate(articles, start=1):

        title = article.get("title", "")
        description = article.get("description", "")
        source = article.get("source", "")
        published_at = article.get("published_at", "")
        url = article.get("url", "")

        entities = []

        for entity in article.get("entities", []):

            symbol = entity.get("symbol")
            name = entity.get("name")
            sentiment = entity.get("sentiment_score")

            if symbol or name:

                entities.append(
                    f"{name or ''} "
                    f"({symbol or ''}) "
                    f"sentiment={sentiment}"
                )

        entity_text = ", ".join(entities)

        news_text.append(
            f"""
============================================================
NEWS {index}
============================================================

TITLE:
{title}

DESCRIPTION:
{description}

SOURCE:
{source}

PUBLISHED:
{published_at}

ENTITIES:
{entity_text}

URL:
{url}
"""
        )

    return "\n".join(news_text)


# ============================================================
# SLOT-SPECIFIC INSTRUCTIONS
# ============================================================

def get_slot_instructions(slot):

    if slot == "PRE_MARKET":

        return """
POST TYPE: PRE-MARKET INTELLIGENCE

The US stock market has not opened yet.

Focus on:

- Important overnight developments
- Major company news
- Economic developments already reported
- Fed-related developments if present in the supplied news
- Major market-moving catalysts
- Important stocks/tickers mentioned in the news
- What investors should be watching when the market opens

Do NOT predict what the market will do.

Make it clear that this is a pre-market update.
"""

    if slot == "MARKET_OPEN":

        return """
POST TYPE: MARKET OPEN UPDATE

The US stock market has opened.

Focus on:

- News affecting the opening session
- Companies or sectors mentioned in the supplied news
- Important developments around the market open
- Why the reported developments matter
- Any actual market information contained in the supplied news

Do NOT invent opening prices or percentage moves.

Make it clear that this is an early-session update.
"""

    if slot == "MID_MARKET":

        return """
POST TYPE: MID-MARKET UPDATE

The US stock market is in the middle of the trading session.

Focus on:

- Important developments since the market opened
- News that may be influencing investors
- Companies/sectors receiving attention
- Major catalysts in the supplied news
- What remains important for the rest of the session

Do NOT invent intraday prices or market movements.

Make it clear that this is a mid-session update.
"""

    if slot == "MARKET_CLOSE":

        return """
POST TYPE: MARKET CLOSE UPDATE

The regular US stock market session has ended.

Focus on:

- The most important developments from the session
- Company and sector news
- Important market-moving stories
- What changed during the session if supported by the supplied news
- What investors may be watching next

Do NOT invent closing prices or percentage moves.

Make it clear that this is a post-market closing update.
"""

    return """
POST TYPE: MANUAL MARKET NEWS UPDATE

Create a general professional US stock market news update
based only on the supplied news.
"""


# ============================================================
# GEMINI AI
# ============================================================

def generate_post(news_text, slot):

    print("Connecting to Gemini...")

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    now_utc = datetime.now(timezone.utc)

    now_et = now_utc.astimezone(ET)

    current_time = now_et.strftime(
        "%Y-%m-%d %I:%M %p ET"
    )

    slot_instructions = get_slot_instructions(slot)

    prompt = f"""
You are a professional US financial news editor.

CURRENT US EASTERN TIME:
{current_time}

CURRENT POST TYPE:
{slot}

============================================================
POST TYPE INSTRUCTIONS
============================================================

{slot_instructions}

============================================================
EDITORIAL RULES
============================================================

You are working with REAL financial news retrieved from
Marketaux.

Use ONLY facts contained in the supplied news.

NEVER invent:

- stock prices
- percentage moves
- market index levels
- earnings numbers
- revenue
- guidance
- economic data
- analyst targets
- Fed statements
- company announcements
- quotes
- dates
- statistics

If a fact is not available in the supplied news,
DO NOT make it up.

Do not present speculation as confirmed fact.

Do not copy article text word-for-word.

Do not give financial advice.

Do not tell users to:

- Buy
- Sell
- Short
- Hold

Do not use:

- guaranteed
- risk-free
- will definitely rise
- will definitely fall
- will crash
- will explode

Only mention a ticker when the ticker is actually present
in the supplied data.

============================================================
CONTENT QUALITY
============================================================

Write like a professional financial media account.

The content should be:

- concise
- credible
- informative
- easy to understand
- engaging
- investor-focused
- suitable for Instagram, Facebook and X

The most important goal is:

Explain WHAT happened and WHY it matters.

Do not turn ordinary news into sensational breaking news.

If several articles discuss the same event, combine them
instead of repeating the same information.

Prioritize the most important and market-relevant story.

============================================================
RETURN EXACTLY THIS FORMAT
============================================================

HEADLINE:
<short professional headline>

HOOK:
<one strong sentence>

WHAT_HAPPENED:
<2-3 concise sentences>

WHY_IT_MATTERS:
<2-3 concise sentences>

TICKERS:
<ticker list or N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<social-media-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source names>

============================================================
REAL NEWS DATA
============================================================

{news_text}
"""

    print("Sending request to Gemini...")

    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input=prompt,
        store=False,
    )

    post = interaction.output_text

    if not post:
        raise RuntimeError(
            "Gemini returned empty response"
        )

    return post


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("US MARKET AUTO NEWS")
    print("=" * 70)

    now_et = datetime.now(ET)

    print(
        f"US Eastern Time: "
        f"{now_et.strftime('%Y-%m-%d %I:%M:%S %p ET')}"
    )

    # --------------------------------------------------------
    # DETERMINE MARKET SLOT
    # --------------------------------------------------------

    slot = get_market_slot()

    # --------------------------------------------------------
    # MANUAL WORKFLOW RUN
    # --------------------------------------------------------

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    if github_event == "workflow_dispatch":

        slot = "MANUAL"

        print(
            "\nManual workflow detected."
        )

    # --------------------------------------------------------
    # SCHEDULED RUN AT WRONG DST DUPLICATE TIME
    # --------------------------------------------------------

    if not slot:

        print(
            "\nNo valid market-news slot at this time."
        )

        print(
            "Exiting without generating a post."
        )

        return

    print(
        f"\nPOST SLOT: {slot}"
    )

    # --------------------------------------------------------
    # STEP 1
    # --------------------------------------------------------

    print(
        "\n[1/3] Fetching US market news..."
    )

    articles = get_market_news()

    print(
        f"Received {len(articles)} news articles."
    )

    # --------------------------------------------------------
    # STEP 2
    # --------------------------------------------------------

    print(
        "\n[2/3] Preparing news for AI..."
    )

    news_text = prepare_news(
        articles
    )

    # --------------------------------------------------------
    # STEP 3
    # --------------------------------------------------------

    print(
        "\n[3/3] Generating post with Gemini..."
    )

    post = generate_post(
        news_text,
        slot
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print("\n")
    print("=" * 70)
    print("GENERATED POST")
    print("=" * 70)

    print(post)

    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
