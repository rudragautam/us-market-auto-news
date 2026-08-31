import os
import requests
from datetime import datetime, timezone, timedelta
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
# US EASTERN TIME
# ============================================================

ET = ZoneInfo("America/New_York")


# ============================================================
# MARKET SLOT
# ============================================================

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
    # AFTER MARKET OPEN
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
    # AFTER MARKET CLOSE
    # 4:15 PM ET
    # --------------------------------------------------------

    if hour == 16 and minute == 15:
        return "MARKET_CLOSE"

    return None


# ============================================================
# GET US MARKET NEWS
# ============================================================

# ============================================================
# GET US MARKET NEWS
# ============================================================

def get_market_news():

    url = "https://api.marketaux.com/v1/news/all"

    # Get news from the last 24 hours.
    # IMPORTANT:
    # Marketaux expects this date format WITHOUT trailing "Z".
    from datetime import timedelta

    published_after = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    params = {
        "api_token": MARKETAUX_API_KEY,
        "countries": "us",
        "language": "en",
        "filter_entities": "true",
        "must_have_entities": "true",

        # Keep this low for free-tier compatibility.
        "limit": 3,

        # IMPORTANT: no Z at the end
        "published_after": published_after,
    }

    print("Requesting Marketaux news...")
    print(f"Published after: {published_after} UTC")

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    # Print useful error information if Marketaux rejects request
    if not response.ok:
        print("Marketaux API Error:")
        print(response.text)

    response.raise_for_status()

    data = response.json()

    articles = data.get("data", [])

    if not articles:
        raise RuntimeError(
            "No US market news returned by Marketaux"
        )

    return articles


# ============================================================
# CLEAN + RANK NEWS
# ============================================================

def select_best_articles(articles):

    scored = []

    # Keywords that usually indicate stronger market relevance.
    important_keywords = [
        "fed",
        "federal reserve",
        "interest rate",
        "inflation",
        "cpi",
        "ppi",
        "jobs",
        "employment",
        "payroll",
        "gdp",
        "recession",
        "tariff",
        "trade",
        "earnings",
        "revenue",
        "guidance",
        "merger",
        "acquisition",
        "lawsuit",
        "regulator",
        "sec",
        "bank",
        "banking",
        "oil",
        "crude",
        "nasdaq",
        "dow",
        "s&p",
        "stock",
        "shares",
        "market",
    ]

    for article in articles:

        title = (
            article.get("title") or ""
        ).strip()

        description = (
            article.get("description") or ""
        ).strip()

        text = (
            title + " " + description
        ).lower()

        score = 0

        # Stronger score for market-relevant terms.
        for keyword in important_keywords:

            if keyword in text:
                score += 2

        # Prefer articles with a proper title.
        if title:
            score += 2

        # Prefer articles with descriptions.
        if description:
            score += 1

        # Prefer articles with identified entities.
        entities = article.get("entities") or []

        if entities:
            score += 2

        # Prefer recent stories.
        published = article.get("published_at")

        if published:
            try:
                published_dt = datetime.fromisoformat(
                    published.replace("Z", "+00:00")
                )

                age_hours = (
                    datetime.now(timezone.utc)
                    - published_dt
                ).total_seconds() / 3600

                if age_hours <= 3:
                    score += 5

                elif age_hours <= 6:
                    score += 4

                elif age_hours <= 12:
                    score += 3

                elif age_hours <= 24:
                    score += 1

            except Exception:
                pass

        scored.append(
            (score, article)
        )

    # Highest score first.
    scored.sort(
        key=lambda item: item[0],
        reverse=True
    )

    # Keep only the best few candidates.
    # Gemini will receive these as candidates,
    # but will be explicitly forced to select ONE.
    return [
        article
        for score, article in scored[:5]
    ]


# ============================================================
# PREPARE NEWS FOR AI
# ============================================================

def prepare_news(articles):

    news_text = []

    for index, article in enumerate(
        articles,
        start=1
    ):

        title = article.get(
            "title",
            ""
        )

        description = article.get(
            "description",
            ""
        )

        source = article.get(
            "source",
            ""
        )

        published_at = article.get(
            "published_at",
            ""
        )

        url = article.get(
            "url",
            ""
        )

        entities = []

        for entity in article.get(
            "entities",
            []
        ):

            symbol = entity.get(
                "symbol"
            )

            name = entity.get(
                "name"
            )

            sentiment = entity.get(
                "sentiment_score"
            )

            if symbol or name:

                entities.append(
                    f"{name or ''} "
                    f"({symbol or ''}) "
                    f"sentiment={sentiment}"
                )

        entity_text = ", ".join(
            entities
        )

        news_text.append(
            f"""
============================================================
CANDIDATE NEWS {index}
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

    return "\n".join(
        news_text
    )


# ============================================================
# SLOT INSTRUCTIONS
# ============================================================

def get_slot_instructions(slot):

    instructions = {

        "PRE_MARKET": """
POST TYPE: PRE-MARKET UPDATE

The US regular stock market has not opened yet.

Focus on the single most important fresh market story
investors should know before the opening bell.

Prefer:
- major company developments
- major economic developments
- Fed-related developments
- important regulatory developments
- major market-moving catalysts

Do not predict market direction.
""",

        "MARKET_OPEN": """
POST TYPE: EARLY MARKET UPDATE

The US regular stock market has already opened.

Focus on the single most important fresh story relevant
to the early trading session.

Do not invent opening prices or percentage moves.
""",

        "MID_MARKET": """
POST TYPE: MID-MARKET UPDATE

The US stock market is in the middle of the trading session.

Focus on the single most important fresh development
relevant to the current session.

Do not invent intraday prices or percentage moves.
""",

        "MARKET_CLOSE": """
POST TYPE: POST-MARKET UPDATE

The regular US stock market session has ended.

Focus on the single most important story from the session
or the most important newly reported development.

Do not invent closing prices or percentage moves.
""",

        "MANUAL": """
POST TYPE: MANUAL MARKET NEWS UPDATE

Create one professional US market news post based on
the single strongest candidate story.
"""
    }

    return instructions.get(
        slot,
        instructions["MANUAL"]
    )


# ============================================================
# GEMINI
# ============================================================

def generate_post(
    news_text,
    slot
):

    print(
        "Connecting to Gemini..."
    )

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    now_utc = datetime.now(
        timezone.utc
    )

    now_et = now_utc.astimezone(
        ET
    )

    current_time = now_et.strftime(
        "%Y-%m-%d %I:%M %p ET"
    )

    slot_instructions = (
        get_slot_instructions(slot)
    )

    prompt = f"""
You are a professional US financial news editor.

CURRENT US EASTERN TIME:
{current_time}

POST SLOT:
{slot}

{slot_instructions}

============================================================
CRITICAL STORY SELECTION RULE
============================================================

You have been given multiple candidate news articles.

YOU MUST SELECT EXACTLY ONE PRIMARY NEWS STORY.

This is extremely important.

Do NOT combine unrelated articles.

Do NOT create a story using information from multiple
different events.

Once you select the strongest candidate, ALL sections of
the final post must be based ONLY on that ONE candidate.

You may use its title, description, source, entities,
published time and URL.

Do not use facts from another candidate.

If two candidates are clearly about the SAME event,
you may use them together.

Otherwise, choose ONE.

============================================================
FACTUAL ACCURACY
============================================================

Use ONLY facts contained in the supplied candidate news.

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

If a fact is not supplied, do not mention it.

Do not present speculation as confirmed fact.

Do not copy article text word-for-word.

Do not give financial advice.

Never tell users to buy, sell, short or hold.

Do not use:

- guaranteed
- risk-free
- will definitely rise
- will definitely fall
- will crash
- will explode

Only mention a ticker if it is actually present
in the selected candidate.

============================================================
EDITORIAL STYLE
============================================================

Write like a professional financial media account.

Tone:

- credible
- concise
- factual
- informative
- investor-focused
- easy to understand
- engaging but not sensational

The goal is:

WHAT happened?
WHY does it matter?

Do not manufacture urgency.

Do not call something "breaking" unless the supplied
information clearly supports that characterization.

============================================================
OUTPUT FORMAT
============================================================

Return EXACTLY this format:

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
<Instagram/Facebook/X-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source name>

URL:
<original selected article URL>

SELECTED_STORY:
<CANDIDATE NEWS number selected>

============================================================
CANDIDATE NEWS
============================================================

{news_text}
"""

    print(
        "Sending request to Gemini..."
    )

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

    now_et = datetime.now(
        ET
    )

    print(
        "US Eastern Time: "
        + now_et.strftime(
            "%Y-%m-%d %I:%M:%S %p ET"
        )
    )

    # --------------------------------------------------------
    # DETERMINE SLOT
    # --------------------------------------------------------

    slot = get_market_slot()

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    # Manual testing is always allowed.
    if github_event == "workflow_dispatch":

        slot = "MANUAL"

        print(
            "\nManual workflow detected."
        )

    # --------------------------------------------------------
    # SAFETY EXIT
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
        "\n[1/4] Fetching recent US market news..."
    )

    articles = get_market_news()

    print(
        f"Received {len(articles)} articles."
    )

    # --------------------------------------------------------
    # STEP 2
    # --------------------------------------------------------

    print(
        "\n[2/4] Ranking market-relevant stories..."
    )

    selected_articles = (
        select_best_articles(
            articles
        )
    )

    if not selected_articles:

        raise RuntimeError(
            "Could not select market news candidates"
        )

    print(
        f"Selected {len(selected_articles)} "
        "candidate stories for AI."
    )

    # --------------------------------------------------------
    # STEP 3
    # --------------------------------------------------------

    print(
        "\n[3/4] Preparing news for AI..."
    )

    news_text = prepare_news(
        selected_articles
    )

    # --------------------------------------------------------
    # STEP 4
    # --------------------------------------------------------

    print(
        "\n[4/4] Generating ONE story with Gemini..."
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
