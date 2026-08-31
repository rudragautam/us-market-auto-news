import os
import base64
from datetime import datetime, timezone
from pathlib import Path

import requests
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
# MODELS
# ============================================================

TEXT_MODEL = "gemini-3.6-flash"

# Nano Banana 2 - Gemini native image generation
IMAGE_MODEL = "gemini-3.1-flash-image"


# ============================================================
# OUTPUT DIRECTORY
# ============================================================

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

POST_FILE = OUTPUT_DIR / "market_news_post.txt"
IMAGE_FILE = OUTPUT_DIR / "market_news.png"


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

--------------------------------------------------
"""
        )

    return "\n".join(news_text)


# ============================================================
# GENERATE TEXT POST
# ============================================================

def generate_post(news_text):

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    current_time = datetime.now(
        timezone.utc
    ).strftime("%Y-%m-%d %H:%M UTC")

    prompt = f"""
You are a professional US stock market news editor.

Current UTC time:
{current_time}

Below is REAL market news retrieved from Marketaux.

Create ONE social-media-ready US market news post.

IMPORTANT RULES:

1. Use ONLY facts present in the supplied news.
2. NEVER invent stock prices.
3. NEVER invent percentages.
4. NEVER invent earnings numbers.
5. NEVER invent Fed statements.
6. NEVER invent company announcements.
7. NEVER invent dates or statistics.
8. Do not present speculation as fact.
9. If information is insufficient, say so.
10. Do not copy article text word-for-word.
11. Keep the writing concise and engaging.
12. Focus on why the news matters to investors.
13. Mention company/ticker when available.
14. Do not give financial advice.
15. Do not say:
    buy
    sell
    guaranteed
    will rise
    will crash

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

    print("Connecting to Gemini text model...")

    interaction = client.interactions.create(
        model=TEXT_MODEL,
        input=prompt,
        store=False,
    )

    post = interaction.output_text

    if not post:
        raise RuntimeError(
            "Gemini returned empty text response"
        )

    return post


# ============================================================
# SAVE TEXT POST
# ============================================================

def save_post(post):

    POST_FILE.write_text(
        post,
        encoding="utf-8"
    )

    print(
        f"Text post saved: {POST_FILE}"
    )


# ============================================================
# EXTRACT HEADLINE
# ============================================================

def extract_headline(post):

    headline = "US Market News"

    for line in post.splitlines():

        if line.startswith("HEADLINE:"):

            value = line.replace(
                "HEADLINE:",
                "",
                1
            ).strip()

            if value:
                headline = value

            break

    return headline


# ============================================================
# GENERATE AI IMAGE
# ============================================================

def generate_market_image(post):

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    headline = extract_headline(post)

    image_prompt = f"""
Create a premium professional US financial news graphic
for a social media post.

NEWS HEADLINE:
{headline}

NEWS CONTEXT:
{post}

VISUAL STYLE:

- Professional financial-news journalism
- Bloomberg / Reuters / CNBC inspired visual language
- Premium editorial composition
- Modern Wall Street atmosphere
- US financial markets theme
- Realistic cinematic lighting
- Sophisticated dark financial-news aesthetic
- Strong visual hierarchy
- Clean composition
- Suitable for Instagram and Facebook
- 16:9 landscape composition

IMPORTANT FACTUAL RULES:

- Do NOT invent stock prices.
- Do NOT invent percentages.
- Do NOT invent financial numbers.
- Do NOT create fake charts containing numbers.
- Do NOT create fake statistics.
- Do NOT imply information that is not contained
  in the supplied news.

TEXT ON IMAGE:

Use the supplied headline as the main headline.

Keep the headline short, clean and highly readable.

Do NOT add paragraphs of text.

Do NOT add fake ticker prices.

Do NOT add fake financial data.

Create a visually compelling editorial image that
communicates the subject of the news without inventing facts.
"""

    print("Generating AI market image...")

    interaction = client.interactions.create(
        model=IMAGE_MODEL,
        input=image_prompt,
        response_format={
            "type": "image",
            "aspect_ratio": "16:9",
        },
    )

    generated_image = interaction.output_image

    if not generated_image:
        raise RuntimeError(
            "Gemini did not return an image"
        )

    image_data = base64.b64decode(
        generated_image.data
    )

    IMAGE_FILE.write_bytes(image_data)

    print(
        f"AI image saved: {IMAGE_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("US MARKET AUTO NEWS")
    print("=" * 70)

    print("\n[1/4] Fetching US market news...")

    articles = get_market_news()

    print(
        f"Received {len(articles)} news articles."
    )

    print("\n[2/4] Preparing news for AI...")

    news_text = prepare_news(
        articles
    )

    print("\n[3/4] Generating text post...")

    post = generate_post(
        news_text
    )

    save_post(post)

    print("\n")
    print("=" * 70)
    print("GENERATED POST")
    print("=" * 70)

    print(post)

    print("=" * 70)

    print("\n[4/4] Generating AI image...")

    generate_market_image(
        post
    )

    print("\n")
    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)

    print(
        f"Text:  {POST_FILE}"
    )

    print(
        f"Image: {IMAGE_FILE}"
    )

    print("=" * 70)


if __name__ == "__main__":
    main()
