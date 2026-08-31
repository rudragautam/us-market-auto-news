import os
import requests
from datetime import datetime, timezone

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
# GEMINI AI
# ============================================================

def generate_post(news_text):

    print("Connecting to Gemini...")

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    current_time = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    prompt = f"""
You are a professional US stock market news editor.

Current UTC time:
{current_time}

You are given REAL financial news retrieved from Marketaux.

Your job is to create ONE high-quality social-media-ready
US stock market news post.

============================================================
STRICT FACTUAL RULES
============================================================

1. Use ONLY information present in the supplied news.

2. NEVER invent:
   - stock prices
   - percentage moves
   - earnings numbers
   - revenue
   - guidance
   - Fed statements
   - economic data
   - analyst targets
   - company announcements

3. Never present speculation as confirmed fact.

4. If the supplied information is insufficient,
   clearly say that the information is insufficient.

5. Do not copy article text word-for-word.

6. Do not fabricate quotes.

7. Do not give financial advice.

8. Do not tell people to:
   - Buy
   - Sell
   - Short
   - Hold

9. Do not use phrases such as:
   - guaranteed
   - will definitely rise
   - will definitely crash
   - risk-free

10. Mention ticker symbols only when they are actually
    present in the supplied data.

============================================================
CONTENT STYLE
============================================================

The post should feel like professional financial media.

Style:

- Clear
- Fast
- Credible
- Concise
- Investor-focused
- Easy to understand
- No unnecessary hype

Explain WHY the news matters.

============================================================
RETURN EXACTLY THIS FORMAT
============================================================

HEADLINE:
<short strong headline>

HOOK:
<one compelling sentence>

WHAT_HAPPENED:
<2-3 concise sentences>

WHY_IT_MATTERS:
<2-3 concise sentences explaining market relevance>

TICKERS:
<ticker list or N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<Instagram/Facebook-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source names>

============================================================
NEWS DATA
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

    print("=" * 60)
    print("US MARKET AUTO NEWS")
    print("=" * 60)

    # --------------------------------------------------------
    # STEP 1
    # --------------------------------------------------------

    print("\n[1/3] Fetching US market news...")

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
        news_text
    )

    # --------------------------------------------------------
    # OUTPUT
    # --------------------------------------------------------

    print("\n")
    print("=" * 60)
    print("GENERATED POST")
    print("=" * 60)

    print(post)

    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
