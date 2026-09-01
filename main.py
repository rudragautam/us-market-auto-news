import os
import requests
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google import genai


# ============================================================
# CONFIG
# ============================================================

MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY")

if not MARKETAUX_API_KEY:
    raise RuntimeError("MARKETAUX_API_KEY secret is missing")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY secret is missing")

if not POLLINATIONS_API_KEY:
    raise RuntimeError("POLLINATIONS_API_KEY secret is missing")


# ============================================================
# CONFIGURATION
# ============================================================

TEXT_MODEL = "gemini-3.6-flash"

ET = ZoneInfo("America/New_York")

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

POST_FILE = OUTPUT_DIR / "market_news_post.txt"
IMAGE_FILE = OUTPUT_DIR / "market_news.png"


# ============================================================
# MARKET SLOT
# ============================================================

def get_market_slot():

    now_et = datetime.now(ET)

    hour = now_et.hour
    minute = now_et.minute

    if hour == 8 and minute == 30:
        return "PRE_MARKET"

    if hour == 10 and minute == 0:
        return "MARKET_OPEN"

    if hour == 13 and minute == 0:
        return "MID_MARKET"

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
        "limit": 3,
    }

    print("Requesting Marketaux news...")

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

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
# PREPARE NEWS
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

============================================================
"""
        )

    return "\n".join(news_text)


# ============================================================
# GEMINI TEXT GENERATION
# ============================================================

def generate_post(news_text, slot):

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    now_et = datetime.now(
        ET
    ).strftime(
        "%Y-%m-%d %I:%M %p ET"
    )

    prompt = f"""
You are a professional US financial news editor.

CURRENT US EASTERN TIME:
{now_et}

POST SLOT:
{slot}

============================================================
VERY IMPORTANT
============================================================

You have multiple candidate news articles.

SELECT EXACTLY ONE PRIMARY STORY.

Do NOT combine unrelated stories.

If stories are about different events,
choose only ONE.

All sections of the final post must be based
on the SAME selected story.

============================================================
FACTUAL ACCURACY
============================================================

Use ONLY information supplied in the selected article.

Never invent:

- stock prices
- percentage changes
- earnings numbers
- revenue
- guidance
- Fed statements
- analyst targets
- statistics
- quotes
- dates
- company announcements

Do not give financial advice.

Do not say:

buy
sell
guaranteed
will rise
will crash
risk-free

Do not copy the article word-for-word.

============================================================
STYLE
============================================================

Professional financial journalism.

Concise.
Credible.
Investor-focused.
Easy to understand.

Explain:

WHAT happened?

WHY does it matter?

Do not use sensational or misleading language.

============================================================
OUTPUT FORMAT
============================================================

Return exactly:

HEADLINE:
<short professional headline>

HOOK:
<one sentence>

WHAT_HAPPENED:
<2-3 sentences>

WHY_IT_MATTERS:
<2-3 sentences>

TICKERS:
<ticker list or N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<social-media-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source name>

URL:
<original article URL>

SELECTED_STORY:
<NEWS number>

============================================================
NEWS
============================================================

{news_text}
"""

    print(
        "Connecting to Gemini text model..."
    )

    interaction = client.interactions.create(
        model=TEXT_MODEL,
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
# SAVE POST
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
# EXTRACT INFORMATION
# ============================================================

def extract_field(
    post,
    field_name
):

    for line in post.splitlines():

        if line.startswith(
            field_name + ":"
        ):

            return line.split(
                ":",
                1
            )[1].strip()

    return ""


# ============================================================
# GENERATE IMAGE USING POLLINATIONS
# ============================================================

def generate_market_image(post, slot):

    headline = extract_field(
        post,
        "HEADLINE"
    )

    tickers = extract_field(
        post,
        "TICKERS"
    )

    sentiment = extract_field(
        post,
        "SENTIMENT"
    )

    print(
        "Generating image using Pollinations..."
    )

    # --------------------------------------------------------
    # Professional financial-news image prompt
    # --------------------------------------------------------

    image_prompt = f"""
Create a premium professional US financial news graphic.

HEADLINE:
{headline}

TICKERS:
{tickers}

SENTIMENT:
{sentiment}

POST SLOT:
{slot}

VISUAL DIRECTION:

Professional financial journalism aesthetic.

Modern Wall Street newsroom atmosphere.

New York Stock Exchange inspired environment.

Premium editorial photography.

Cinematic lighting.

Realistic financial-market environment.

Elegant dark blue and black financial-news visual style.

Subtle stock-market screens in the background.

No fake numerical data.

No fake stock prices.

No fake percentages.

No fake charts.

No fake financial statistics.

The main headline must be clearly visible.

Create a strong visual hierarchy.

The headline should be short, clean and readable.

Use professional typography.

Do not add paragraphs.

Do not add unrelated companies.

Do not add unrelated logos.

Do not invent facts.

The image should look like a professionally produced
Bloomberg / Reuters / CNBC-style financial news graphic.

16:9 landscape composition.
"""

    # URL encode prompt automatically through requests
    url = "https://gen.pollinations.ai/image/" + requests.utils.quote(
        image_prompt,
        safe=""
    )

    headers = {
        "Authorization": f"Bearer {POLLINATIONS_API_KEY}",
        "Accept": "image/png",
    }

    params = {
        "model": "flux",
        "width": 1280,
        "height": 720,
        "nologo": "true",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=180
    )

    if not response.ok:

        print(
            "Pollinations API Error:"
        )

        print(
            response.text
        )

        response.raise_for_status()

    content_type = response.headers.get(
        "content-type",
        ""
    ).lower()

    if "image" not in content_type:

        raise RuntimeError(
            "Pollinations did not return an image. "
            f"Content-Type: {content_type}"
        )

    IMAGE_FILE.write_bytes(
        response.content
    )

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
    # MARKET SLOT
    # --------------------------------------------------------

    slot = get_market_slot()

    github_event = os.environ.get(
        "GITHUB_EVENT_NAME",
        ""
    )

    # Manual testing
    if github_event == "workflow_dispatch":

        slot = "MANUAL"

        print(
            "\nManual workflow detected."
        )

    if not slot:

        print(
            "\nNo valid market-news slot."
        )

        print(
            "Exiting."
        )

        return

    print(
        f"\nPOST SLOT: {slot}"
    )

    # --------------------------------------------------------
    # STEP 1
    # --------------------------------------------------------

    print(
        "\n[1/4] Fetching US market news..."
    )

    articles = get_market_news()

    print(
        f"Received {len(articles)} news articles."
    )

    # --------------------------------------------------------
    # STEP 2
    # --------------------------------------------------------

    print(
        "\n[2/4] Preparing news for AI..."
    )

    news_text = prepare_news(
        articles
    )

    # --------------------------------------------------------
    # STEP 3
    # --------------------------------------------------------

    print(
        "\n[3/4] Generating text post..."
    )

    post = generate_post(
        news_text,
        slot
    )

    save_post(
        post
    )

    print("\n")
    print("=" * 70)
    print("GENERATED POST")
    print("=" * 70)

    print(
        post
    )

    print(
        "=" * 70
    )

    # --------------------------------------------------------
    # STEP 4
    # --------------------------------------------------------

    print(
        "\n[4/4] Generating AI image..."
    )

    generate_market_image(
        post,
        slot
    )

    print("\n")
    print("=" * 70)
    print("SUCCESS")
    print("=" * 70)

    print(
        f"Text file : {POST_FILE}"
    )

    print(
        f"Image file: {IMAGE_FILE}"
    )

    print(
        "=" * 70
    )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
