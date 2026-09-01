import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont
from google import genai


# ============================================================
# CONFIG
# ============================================================

MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
POLLINATIONS_API_KEY = os.environ.get("POLLINATIONS_API_KEY")

OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

POST_FILE = OUTPUT_DIR / "market_news_post.txt"
IMAGE_FILE = OUTPUT_DIR / "market_news_image.png"

POLLINATIONS_MODEL = "flux"

IMAGE_WIDTH = 1280
IMAGE_HEIGHT = 720


# ============================================================
# VALIDATE SECRETS
# ============================================================

if not MARKETAUX_API_KEY:
    raise RuntimeError("MARKETAUX_API_KEY secret is missing")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY secret is missing")

if not POLLINATIONS_API_KEY:
    raise RuntimeError("POLLINATIONS_API_KEY secret is missing")


# ============================================================
# HELPERS
# ============================================================

def clean_text(value):
    if value is None:
        return ""

    value = str(value)

    value = value.replace("\x00", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def safe_filename(text):
    text = clean_text(text)

    text = re.sub(
        r"[^a-zA-Z0-9_\- ]+",
        "",
        text
    )

    text = re.sub(r"\s+", "_", text)

    return text[:80] or "market_news"


# ============================================================
# GET US MARKET NEWS
# ============================================================

def get_market_news():

    print("Requesting Marketaux news...")

    url = "https://api.marketaux.com/v1/news/all"

    params = {
        "api_token": MARKETAUX_API_KEY,
        "countries": "us",
        "language": "en",
        "filter_entities": "true",
        "must_have_entities": "true",
        "limit": 10,
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    if response.status_code != 200:

        print("Marketaux response:")
        print(response.text[:2000])

        response.raise_for_status()

    data = response.json()

    articles = data.get("data", [])

    if not articles:
        raise RuntimeError(
            "No US market news returned by Marketaux"
        )

    print(f"Received {len(articles)} news articles.")

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

        title = clean_text(
            article.get("title", "")
        )

        description = clean_text(
            article.get("description", "")
        )

        source = clean_text(
            article.get("source", "")
        )

        published_at = clean_text(
            article.get("published_at", "")
        )

        url = clean_text(
            article.get("url", "")
        )

        entities = []

        for entity in article.get(
            "entities",
            []
        ):

            symbol = clean_text(
                entity.get("symbol", "")
            )

            name = clean_text(
                entity.get("name", "")
            )

            sentiment = entity.get(
                "sentiment_score"
            )

            if symbol or name:

                entity_text = (
                    f"{name or 'Unknown'} "
                    f"({symbol or 'N/A'}) "
                    f"sentiment={sentiment}"
                )

                entities.append(
                    entity_text
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
"""
        )

    return "\n".join(news_text)


# ============================================================
# GEMINI TEXT GENERATION
# ============================================================

def generate_market_post(
    articles,
    news_text
):

    print("Connecting to Gemini text model...")

    client = genai.Client(
        api_key=GEMINI_API_KEY
    )

    current_time = datetime.now(
        timezone.utc
    ).strftime(
        "%Y-%m-%d %H:%M UTC"
    )

    prompt = f"""
You are a professional US stock market
news editor.

Current UTC time:
{current_time}

You are given REAL US financial news
retrieved from Marketaux.

Your job:

1. Select ONE news article that is the
   strongest and most relevant story for
   a US stock-market social media post.

2. Use ONLY information present in the
   supplied news.

3. NEVER invent:
   - stock prices
   - percentages
   - earnings
   - revenue
   - Fed statements
   - company announcements
   - dates
   - financial numbers

4. Do not combine unrelated stories.

5. Do not make speculation sound like fact.

6. Do not give financial advice.

7. Do not say:
   buy
   sell
   guaranteed
   will rise
   will crash

8. The image will be generated separately.
   Therefore DO NOT write an image prompt.

9. The selected story must be the same story
   represented by the headline and explanation.

10. Tickers must come only from the selected story.

IMPORTANT:

Return EXACTLY this format.

SELECTED_NEWS_INDEX:
<number from 1 to 10>

HEADLINE:
<short, accurate headline>

HOOK:
<one engaging sentence>

WHAT_HAPPENED:
<2-3 sentences explaining the event>

WHY_IT_MATTERS:
<2-3 sentences explaining investor relevance
without giving financial advice>

TICKERS:
<ticker list, or N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<Instagram/Facebook-ready caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source name>

NEWS DATA:
{news_text}
"""

    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input=prompt,
        store=False,
    )

    post = getattr(
        interaction,
        "output_text",
        None
    )

    if not post:
        raise RuntimeError(
            "Gemini returned empty response"
        )

    post = post.strip()

    return post


# ============================================================
# PARSE GEMINI OUTPUT
# ============================================================

def get_field(
    text,
    field_name,
    next_fields=None
):

    if next_fields is None:
        next_fields = []

    pattern = rf"{re.escape(field_name)}:\s*(.*?)(?=\n(?:"

    if next_fields:

        pattern += "|".join(
            re.escape(x)
            for x in next_fields
        )

    pattern += r"):\s*|\Z)"

    match = re.search(
        pattern,
        text,
        flags=re.IGNORECASE | re.DOTALL
    )

    if not match:
        return ""

    return clean_text(
        match.group(1)
    )


def parse_post(post):

    fields = [
        "SELECTED_NEWS_INDEX",
        "HEADLINE",
        "HOOK",
        "WHAT_HAPPENED",
        "WHY_IT_MATTERS",
        "TICKERS",
        "SENTIMENT",
        "CAPTION",
        "HASHTAGS",
        "SOURCE",
    ]

    result = {}

    for i, field in enumerate(fields):

        next_fields = fields[i + 1:]

        result[field] = get_field(
            post,
            field,
            next_fields
        )

    # --------------------------------------------------------
    # SELECTED NEWS INDEX
    # --------------------------------------------------------

    try:

        selected_index = int(
            re.search(
                r"\d+",
                result.get(
                    "SELECTED_NEWS_INDEX",
                    "1"
                )
            ).group()
        )

    except Exception:

        selected_index = 1

    if selected_index < 1:
        selected_index = 1

    if selected_index > 10:
        selected_index = 10

    result["SELECTED_NEWS_INDEX"] = (
        selected_index
    )

    return result


# ============================================================
# CREATE IMAGE PROMPT
# ============================================================

def build_image_prompt(
    article,
    parsed_post
):

    headline = parsed_post.get(
        "HEADLINE",
        ""
    )

    what_happened = parsed_post.get(
        "WHAT_HAPPENED",
        ""
    )

    tickers = parsed_post.get(
        "TICKERS",
        ""
    )

    source = parsed_post.get(
        "SOURCE",
        ""
    )

    title = clean_text(
        article.get("title", "")
    )

    description = clean_text(
        article.get("description", "")
    )

    entities = []

    for entity in article.get(
        "entities",
        []
    ):

        name = clean_text(
            entity.get("name", "")
        )

        symbol = clean_text(
            entity.get("symbol", "")
        )

        if name or symbol:

            entities.append(
                f"{name} ({symbol})"
            )

    entity_text = ", ".join(
        entities
    )

    prompt = f"""
Create a premium editorial financial-news
photograph for a US stock-market news post.

THIS IS THE EXACT STORY:

Headline:
{headline}

Original news title:
{title}

What happened:
{what_happened}

Original description:
{description}

Companies / entities:
{entity_text}

Ticker:
{tickers}

Source:
{source}

VISUAL INSTRUCTIONS:

Create a realistic cinematic editorial image
that DIRECTLY represents the story above.

The visual subject must match the actual
company, industry, event, or financial theme.

Examples:

- If this is a bank story:
  show a realistic US bank / financial district /
  institutional banking environment.

- If this is a pharmaceutical story:
  show pharmaceutical research, medicine,
  laboratory or healthcare business imagery.

- If this is an AI/technology story:
  show realistic data centers, AI infrastructure,
  semiconductor technology or technology business
  imagery.

- If this is an energy story:
  show oil, gas, electricity, renewable energy
  or relevant infrastructure.

- If this is a Federal Reserve / economic story:
  show a realistic Federal Reserve / US economic /
  monetary-policy environment.

- If this is an executive stock transaction:
  show a realistic corporate executive / corporate
  headquarters / stock-market financial context,
  without depicting a specific real person.

CRITICAL RULES:

DO NOT put ANY text in the image.

DO NOT write:
- headlines
- company names
- ticker symbols
- percentages
- prices
- captions
- logos
- watermarks
- random words
- fake stock symbols
- fake financial numbers

DO NOT generate a generic stock-market
trading floor unless the story is actually
about the broader stock market.

DO NOT invent a specific person.

DO NOT create unrelated companies.

The image should look like a professional
Reuters / Bloomberg / Financial Times style
editorial photograph.

Realistic photography.
Premium financial journalism.
Cinematic lighting.
Professional composition.
Sharp details.
Institutional investor atmosphere.

Landscape 16:9 composition.
Leave some clean darker space in the lower
portion for a headline overlay.

ABSOLUTELY NO TEXT IN THE IMAGE.
"""


    return prompt.strip()


# ============================================================
# POLLINATIONS IMAGE GENERATION
# ============================================================

def generate_pollinations_image(
    image_prompt
):

    print("Generating relevant AI market image...")
    print("Pollinations model:", POLLINATIONS_MODEL)

    encoded_prompt = quote(
        image_prompt,
        safe=""
    )

    url = (
        "https://gen.pollinations.ai/image/"
        + encoded_prompt
    )

    params = {
        "model": POLLINATIONS_MODEL,
        "width": IMAGE_WIDTH,
        "height": IMAGE_HEIGHT,
    }

    headers = {
        "Authorization":
            f"Bearer {POLLINATIONS_API_KEY}"
    }

    response = requests.get(
        url,
        params=params,
        headers=headers,
        timeout=180
    )

    if response.status_code != 200:

        print(
            "Pollinations error:"
        )

        print(
            response.text[:2000]
        )

        response.raise_for_status()

    content_type = (
        response.headers
        .get(
            "content-type",
            ""
        )
        .lower()
    )

    if not content_type.startswith(
        "image/"
    ):

        raise RuntimeError(
            "Pollinations did not return "
            f"an image. Content-Type: "
            f"{content_type}"
        )

    with open(
        OUTPUT_DIR / "market_news_raw.png",
        "wb"
    ) as file:

        file.write(
            response.content
        )

    print(
        "Raw AI image saved:"
        " output/market_news_raw.png"
    )


# ============================================================
# LOAD FONT
# ============================================================

def get_font(
    size,
    bold=False
):

    possible_fonts = []

    if bold:

        possible_fonts = [
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans-Bold.ttf",

            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Bold.ttf",
        ]

    else:

        possible_fonts = [
            "/usr/share/fonts/truetype/dejavu/"
            "DejaVuSans.ttf",

            "/usr/share/fonts/truetype/liberation2/"
            "LiberationSans-Regular.ttf",
        ]

    for font_path in possible_fonts:

        if os.path.exists(font_path):

            return ImageFont.truetype(
                font_path,
                size
            )

    return ImageFont.load_default()


# ============================================================
# ADD OUR OWN TEXT OVERLAY
# ============================================================

def create_final_image(
    parsed_post
):

    raw_image_path = (
        OUTPUT_DIR /
        "market_news_raw.png"
    )

    if not raw_image_path.exists():

        raise RuntimeError(
            "Raw Pollinations image not found"
        )

    image = Image.open(
        raw_image_path
    ).convert("RGB")

    # --------------------------------------------------------
    # Resize / crop to 1280x720
    # --------------------------------------------------------

    target_ratio = (
        IMAGE_WIDTH /
        IMAGE_HEIGHT
    )

    current_ratio = (
        image.width /
        image.height
    )

    if current_ratio > target_ratio:

        # Image is wider
        new_height = IMAGE_HEIGHT

        new_width = int(
            image.width *
            (
                IMAGE_HEIGHT /
                image.height
            )
        )

    else:

        # Image is taller
        new_width = IMAGE_WIDTH

        new_height = int(
            image.height *
            (
                IMAGE_WIDTH /
                image.width
            )
        )

    image = image.resize(
        (
            new_width,
            new_height
        ),
        Image.Resampling.LANCZOS
    )

    left = (
        new_width -
        IMAGE_WIDTH
    ) // 2

    top = (
        new_height -
        IMAGE_HEIGHT
    ) // 2

    image = image.crop(
        (
            left,
            top,
            left + IMAGE_WIDTH,
            top + IMAGE_HEIGHT
        )
    )

    # --------------------------------------------------------
    # Overlay
    # --------------------------------------------------------

    overlay = Image.new(
        "RGBA",
        image.size,
        (
            0,
            0,
            0,
            0
        )
    )

    draw = ImageDraw.Draw(
        overlay
    )

    # Dark gradient-like bands
    draw.rectangle(
        (
            0,
            0,
            IMAGE_WIDTH,
            125
        ),
        fill=(
            0,
            0,
            0,
            145
        )
    )

    draw.rectangle(
        (
            0,
            480,
            IMAGE_WIDTH,
            IMAGE_HEIGHT
        ),
        fill=(
            0,
            0,
            0,
            185
        )
    )

    # --------------------------------------------------------
    # Fonts
    # --------------------------------------------------------

    label_font = get_font(
        30,
        bold=True
    )

    headline_font = get_font(
        48,
        bold=True
    )

    ticker_font = get_font(
        28,
        bold=True
    )

    small_font = get_font(
        22,
        bold=False
    )

    # --------------------------------------------------------
    # US MARKET NEWS label
    # --------------------------------------------------------

    draw.text(
        (
            50,
            35
        ),
        "US MARKET NEWS",
        font=label_font,
        fill=(
            255,
            255,
            255,
            255
        )
    )

    # --------------------------------------------------------
    # Headline
    # --------------------------------------------------------

    headline = clean_text(
        parsed_post.get(
            "HEADLINE",
            ""
        )
    )

    if not headline:

        headline = (
            "Latest US Market Development"
        )

    headline_lines = textwrap.wrap(
        headline,
        width=42
    )

    # Maximum 3 lines
    headline_lines = headline_lines[:3]

    y = 500

    for line in headline_lines:

        draw.text(
            (
                50,
                y
            ),
            line,
            font=headline_font,
            fill=(
                255,
                255,
                255,
                255
            ),
            stroke_width=1,
            stroke_fill=(
                0,
                0,
                0,
                180
            )
        )

        y += 58

    # --------------------------------------------------------
    # Tickers
    # --------------------------------------------------------

    tickers = clean_text(
        parsed_post.get(
            "TICKERS",
            ""
        )
    )

    if tickers and tickers.upper() != "N/A":

        draw.text(
            (
                50,
                665
            ),
            f"Ticker: {tickers}",
            font=ticker_font,
            fill=(
                255,
                255,
                255,
                255
            )
        )

    # --------------------------------------------------------
    # Sentiment
    # --------------------------------------------------------

    sentiment = clean_text(
        parsed_post.get(
            "SENTIMENT",
            ""
        )
    )

    if sentiment:

        sentiment_text = (
            f"Sentiment: {sentiment}"
        )

        draw.text(
            (
                1000,
                675
            ),
            sentiment_text,
            font=small_font,
            fill=(
                255,
                255,
                255,
                230
            )
        )

    # --------------------------------------------------------
    # Combine
    # --------------------------------------------------------

    final_image = Image.alpha_composite(
        image.convert("RGBA"),
        overlay
    )

    final_image.convert(
        "RGB"
    ).save(
        IMAGE_FILE,
        "PNG",
        optimize=True
    )

    print(
        f"Final image saved: {IMAGE_FILE}"
    )


# ============================================================
# SAVE POST
# ============================================================

def save_post(
    post,
    parsed_post,
    selected_article
):

    article_url = clean_text(
        selected_article.get(
            "url",
            ""
        )
    )

    selected_title = clean_text(
        selected_article.get(
            "title",
            ""
        )
    )

    final_content = f"""
============================================================
US MARKET NEWS
============================================================

HEADLINE:
{parsed_post.get("HEADLINE", "")}

HOOK:
{parsed_post.get("HOOK", "")}

WHAT_HAPPENED:
{parsed_post.get("WHAT_HAPPENED", "")}

WHY_IT_MATTERS:
{parsed_post.get("WHY_IT_MATTERS", "")}

TICKERS:
{parsed_post.get("TICKERS", "")}

SENTIMENT:
{parsed_post.get("SENTIMENT", "")}

CAPTION:
{parsed_post.get("CAPTION", "")}

HASHTAGS:
{parsed_post.get("HASHTAGS", "")}

SOURCE:
{parsed_post.get("SOURCE", "")}

SELECTED STORY:
{selected_title}

URL:
{article_url}

============================================================
RAW GEMINI RESPONSE
============================================================

{post}
""".strip()

    POST_FILE.write_text(
        final_content,
        encoding="utf-8"
    )

    print(
        f"Text post saved: {POST_FILE}"
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("US MARKET AUTO NEWS")
    print("=" * 60)

    # --------------------------------------------------------
    # 1. NEWS
    # --------------------------------------------------------

    print(
        "\n[1/5] Fetching US market news..."
    )

    articles = get_market_news()

    # --------------------------------------------------------
    # 2. PREPARE
    # --------------------------------------------------------

    print(
        "\n[2/5] Preparing news for AI..."
    )

    news_text = prepare_news(
        articles
    )

    # --------------------------------------------------------
    # 3. GEMINI POST
    # --------------------------------------------------------

    print(
        "\n[3/5] Generating text post..."
    )

    post = generate_market_post(
        articles,
        news_text
    )

    parsed_post = parse_post(
        post
    )

    selected_index = parsed_post[
        "SELECTED_NEWS_INDEX"
    ]

    # Make sure index exists
    if selected_index > len(articles):

        selected_index = 1

    selected_article = articles[
        selected_index - 1
    ]

    print(
        "\nSelected news article:"
    )

    print(
        clean_text(
            selected_article.get(
                "title",
                ""
            )
        )
    )

    # --------------------------------------------------------
    # SAVE POST
    # --------------------------------------------------------

    save_post(
        post,
        parsed_post,
        selected_article
    )

    # --------------------------------------------------------
    # 4. IMAGE
    # --------------------------------------------------------

    print(
        "\n[4/5] Generating relevant AI image..."
    )

    image_prompt = build_image_prompt(
        selected_article,
        parsed_post
    )

    generate_pollinations_image(
        image_prompt
    )

    # --------------------------------------------------------
    # 5. FINAL IMAGE
    # --------------------------------------------------------

    print(
        "\n[5/5] Adding verified headline overlay..."
    )

    create_final_image(
        parsed_post
    )

    # --------------------------------------------------------
    # DONE
    # --------------------------------------------------------

    print("\n")
    print("=" * 60)
    print("GENERATED POST")
    print("=" * 60)

    print(post)

    print("\n")
    print("=" * 60)
    print("OUTPUT FILES")
    print("=" * 60)

    print(
        f"POST : {POST_FILE}"
    )

    print(
        f"IMAGE: {IMAGE_FILE}"
    )

    print("=" * 60)
    print("SUCCESS")
    print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    main()
