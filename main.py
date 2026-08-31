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

    response = requests.get(url, params=params, timeout=30)

    response.raise_for_status()

    data = response.json()

    articles = data.get("data", [])

    if not articles:
        raise RuntimeError("No US market news returned by Marketaux")

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
                    f"{name or ''} ({symbol or ''}) sentiment={sentiment}"
                )

        entity_text = ", ".join(entities)

        news_text.append(
            f"""
NEWS {index}

Title:
{title}

Description:
{description}

Source:
{source}

Published:
{published_at}

Entities:
{entity_text}

URL:
{url}
"""
        )

    return "\n".join(news_text)


# ============================================================
# GEMINI
# ============================================================

def generate_post(news_text):

    client = genai.Client(api_key=GEMINI_API_KEY)

    current_time = datetime.now(timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    prompt = f"""
You are a professional US stock market news editor.

Current UTC time:
{current_time}

Below is REAL market news retrieved from Marketaux.

Your job is to create ONE social-media-ready US market news post.

IMPORTANT RULES:

1. Use ONLY facts present in the supplied news.
2. NEVER invent stock prices, percentages, earnings,
   Fed statements, company announcements or numbers.
3. Do not present speculation as fact.
4. If information is insufficient, say so.
5. Do not copy article text word-for-word.
6. Keep the writing concise and engaging.
7. Focus on why the news matters to investors.
8. Mention the company/ticker when available.
9. Do not give financial advice.
10. Do not say "buy", "sell", "guaranteed", "will rise",
    or "will crash".

Return exactly this format:

HEADLINE:
<short headline>

HOOK:
<one sentence>

WHAT_HAPPENED:
<2-3 sentences>

WHY_IT_MATTERS:
<2-3 sentences>

TICKERS:
<ticker list, or N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<Instagram/Facebook-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source names>

NEWS DATA:
{news_text}
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt
    )

    if not response.text:
        raise RuntimeError("Gemini returned empty response")

    return response.text


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("US MARKET AUTO NEWS")
    print("=" * 60)

    print("\n[1/3] Fetching US market news...")

    articles = get_market_news()

    print(f"Received {len(articles)} news articles.")

    print("\n[2/3] Preparing news for AI...")

    news_text = prepare_news(articles)

    print("\n[3/3] Generating post with Gemini...")

    post = generate_post(news_text)

    print("\n")
    print("=" * 60)
    print("GENERATED POST")
    print("=" * 60)
    print(post)
    print("=" * 60)


if __name__ == "__main__":
    main()
