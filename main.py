import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload


# ============================================================
# CONFIG
# ============================================================

MARKETAUX_API_KEY = os.environ["MARKETAUX_API_KEY"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
YOUTUBE_CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
YOUTUBE_CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
YOUTUBE_REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

OUTPUT_DIR = Path("output")
STATE_PATH = Path("data/posted_news.json")

WIDTH, HEIGHT = 1080, 1920
SLIDE_SECONDS = 5
FPS = 60
ET = ZoneInfo("America/New_York")

TARGET_SLOTS = {
    (8, 30): "PRE-MARKET",
    (10, 0): "AFTER OPEN",
    (13, 0): "MID-MARKET",
    (16, 15): "AFTER CLOSE",
}

OUTPUT_DIR.mkdir(exist_ok=True, parents=True)
STATE_PATH.parent.mkdir(exist_ok=True, parents=True)


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slot_info():
    now = datetime.now(ET)

    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return "MANUAL TEST", now

    nearest_name = None
    nearest_seconds = 10**9

    for (hour, minute), name in TARGET_SLOTS.items():
        target = now.replace(
            hour=hour,
            minute=minute,
            second=0,
            microsecond=0,
        )
        seconds = abs((now - target).total_seconds())
        if seconds < nearest_seconds:
            nearest_seconds = seconds
            nearest_name = name

    if nearest_seconds > 600:
        print(f"No scheduled slot at {now.strftime('%H:%M:%S %Z')}. Skipping.")
        raise SystemExit(0)

    return nearest_name, now


def load_state():
    if not STATE_PATH.exists():
        return set()

    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(data)
        if isinstance(data, dict):
            return set(data.get("posted_urls", []))
    except Exception as exc:
        print(f"State load skipped: {exc}")

    return set()


def save_state(urls):
    STATE_PATH.write_text(
        json.dumps(sorted(urls), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def bullet_list(text):
    parts = re.split(r"[\n•]+", str(text or ""))
    parts = [clean(x).lstrip("-*").strip() for x in parts if clean(x)]
    return parts[:3]


def ticker_list(text):
    if isinstance(text, (list, tuple)):
        text = ",".join(str(item or "") for item in text)
    parts = re.split(r"[,\n•]+", str(text or ""))
    cleaned = []
    for value in parts:
        value = clean(value).lstrip("$").upper()
        if value and value not in cleaned and value not in {"N/A", "NA", "NONE", "NULL", "-", "—"}:
            cleaned.append(value)
    return cleaned[:6]


# ============================================================
# MARKETAUX
# ============================================================

def get_news():
    url = "https://api.marketaux.com/v1/news/all"
    after = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).strftime("%Y-%m-%dT%H:%M:%S")

    params = {
        "api_token": MARKETAUX_API_KEY,
        "countries": "us",
        "language": "en",
        "filter_entities": "true",
        "must_have_entities": "true",
        "group_similar": "true",
        "limit": 3,
        "published_after": after,
    }

    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    articles = r.json().get("data", [])

    if not articles:
        params.pop("published_after", None)
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        articles = r.json().get("data", [])

    if not articles:
        raise RuntimeError("Marketaux returned no news.")

    return articles


def format_news(articles):
    chunks = []

    for i, a in enumerate(articles, 1):
        entities = []
        for e in a.get("entities", []):
            name = clean(e.get("name"))
            symbol = clean(e.get("symbol"))
            if name or symbol:
                entities.append(f"{name} ({symbol})".strip())

        chunks.append(f"""
NEWS {i}
TITLE: {clean(a.get("title"))}
DESCRIPTION: {clean(a.get("description"))}
SOURCE: {clean(a.get("source"))}
PUBLISHED: {clean(a.get("published_at"))}
ENTITIES: {", ".join(entities)}
URL: {clean(a.get("url"))}
""".strip())

    return "\n\n---\n\n".join(chunks)


# ============================================================
# GEMINI — SHORT, VISUAL-FIRST SCRIPT
# ============================================================

def generate_content(news_text, slot):
    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"""
You are the editor of a premium US stock-market Shorts channel.

POST SLOT: {slot}

Choose ONE strongest story from the supplied Marketaux news.

This is a premium editorial Short, not a coding/demo screen.
Write concise copy that looks natural when printed on a vertical video.

STRICT RULES:
- Use only facts present in the supplied news.
- Never invent numbers, targets, ratings, earnings, dates or quotes.
- Do not give financial advice.
- Prefer a company/equity catalyst over generic filler.
- Tickers only from the selected story.
- If no number is present, say "No material figure reported" instead of N/A.
- If no ticker is present, return NONE.
- Avoid crypto-only stories unless the story clearly affects US equities.
- Every line must be useful to a viewer; never output filler or coding language.
- The hook is the opening reason to keep watching; do NOT write the word "HOOK" inside the sentence.
- Sentiment must be BULLISH, BEARISH, MIXED, or NEUTRAL.

Return EXACTLY these fields:

SELECTED_NEWS_INDEX:
<number>

HEADLINE:
<6-12 word factual headline, specific to the selected company/story>

HOOK:
<one sharp 10-18 word opening sentence explaining why this matters now>

WHAT_HAPPENED:
<3 short bullet lines, each max 12 words>

WHY_IT_MATTERS:
<3 short bullet lines, each max 12 words>

TICKERS:
<comma-separated tickers, or NONE>

KEY_SIGNAL:
<one short factual investor-relevant signal; if none exists, write "No material figure reported">

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<one clean sentence suitable for the post caption>

HASHTAGS:
<8-12 relevant hashtags>

SOURCE:
<source name>

NEWS:
{news_text}
"""

    result = client.interactions.create(
        model="gemini-3.6-flash",
        input=prompt,
        store=False,
    )

    text = getattr(result, "output_text", "")
    if not text:
        raise RuntimeError("Gemini returned no text.")

    return text.strip()


def parse_fields(text):
    names = [
        "SELECTED_NEWS_INDEX", "HEADLINE", "HOOK",
        "WHAT_HAPPENED", "WHY_IT_MATTERS", "TICKERS",
        "KEY_SIGNAL", "SENTIMENT", "CAPTION",
        "HASHTAGS", "SOURCE"
    ]

    out = {}
    for i, name in enumerate(names):
        nxt = names[i + 1:]
        look = "|".join(re.escape(x) for x in nxt)

        if look:
            pattern = rf"(?is)^{name}:\s*(.*?)(?=^\s*(?:{look}):|\Z)"
        else:
            pattern = rf"(?is)^{name}:\s*(.*?)\Z"

        m = re.search(pattern, text, flags=re.MULTILINE)
        out[name] = clean(m.group(1)) if m else ""

    try:
        out["SELECTED_NEWS_INDEX"] = int(
            re.search(r"\d+", out["SELECTED_NEWS_INDEX"]).group()
        )
    except Exception:
        out["SELECTED_NEWS_INDEX"] = 1

    return out


# ============================================================
# HTML TEMPLATE RENDERING
# ============================================================

HTML_TEMPLATE_PATH = Path("templates/market_template.html")


def bullet_list(text):
    parts = re.split(r"[\n•]+", str(text or ""))
    parts = [clean(x).lstrip("-*").strip() for x in parts if clean(x)]
    return parts[:3]


def html_escape(text):
    text = str(text or "")
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
    )


def render_html_template(data, article, slot):
    if not HTML_TEMPLATE_PATH.exists():
        raise RuntimeError(f"Missing {HTML_TEMPLATE_PATH}")

    what = bullet_list(data.get("WHAT_HAPPENED"))
    why = bullet_list(data.get("WHY_IT_MATTERS"))
    tickers = ticker_list(data.get("TICKERS"))
    sentiment = clean(data.get("SENTIMENT")).upper() or "NEUTRAL"
    signal = clean(data.get("KEY_SIGNAL")) or "No material figure reported"
    source = clean(data.get("SOURCE")) or clean(article.get("source")) or "Marketaux"
    source_url = clean(article.get("url"))
    company_names = [clean(e.get("name")) for e in article.get("entities", []) if clean(e.get("name"))]
    entity_tickers = [clean(e.get("symbol")).upper() for e in article.get("entities", []) if clean(e.get("symbol"))]
    caption = clean(data.get("CAPTION")) or clean(data.get("HOOK"))

    sentiment_text = {
        "BULLISH": "Positive market tone is visible in the selected story.",
        "BEARISH": "Negative market tone is visible in the selected story.",
        "MIXED": "The selected story carries mixed signals for investors.",
        "NEUTRAL": "The selected story does not clearly favor either direction.",
    }.get(sentiment, "The selected story does not clearly favor either direction.")

    # Always give Chromium a local, verified image. This prevents source-host
    # hotlink failures and corrupt/unsupported responses reaching the video.
    fallback_path = Path("assets/fallback-market.jpg")
    if not fallback_path.exists():
        raise RuntimeError(f"Missing required fallback image: {fallback_path}")
    local_fallback = OUTPUT_DIR / fallback_path.name
    local_fallback.write_bytes(fallback_path.read_bytes())
    image_url = clean(article.get("image_url"))
    image_src = local_fallback.name
    if image_url:
        try:
            img_response = requests.get(
                image_url,
                timeout=20,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            img_response.raise_for_status()
            content_type = (img_response.headers.get("content-type") or "").lower()
            if not content_type.startswith("image/"):
                raise ValueError("response was not an image")
            ext = ".png" if "png" in content_type else ".webp" if "webp" in content_type else ".jpg"
            image_path = OUTPUT_DIR / f"news_image{ext}"
            image_path.write_bytes(img_response.content)
            with Image.open(image_path) as image:
                image.verify()
            image_src = image_path.name
            print(f"News image ready: {image_url}")
        except Exception as exc:
            print(f"Image download failed; using repository fallback: {exc}")

    values = {
        "HEADLINE": clean(data.get("HEADLINE")) or clean(article.get("title")) or "US Market Update",
        "HOOK": clean(data.get("HOOK")) or clean(article.get("description")) or "A new market development is drawing investor attention.",
        "WHAT_1": what[0] if len(what) > 0 else "Key development reported in the selected story.",
        "WHAT_2": what[1] if len(what) > 1 else "Investors are assessing the potential market impact.",
        "WHAT_3": what[2] if len(what) > 2 else "Company and sector sentiment remain in focus.",
        "WHY_1": why[0] if len(why) > 0 else "The development may affect investor expectations.",
        "WHY_2": why[1] if len(why) > 1 else "Markets are watching the next company update.",
        "WHY_3": why[2] if len(why) > 2 else "Further headlines could move the sector.",
        # Renderer creates cards only from this actual list; never send
        # placeholder ticker slots or invented "driver" labels.
        "TICKERS": tickers,
        "SENTIMENT": sentiment,
        "SENTIMENT_TEXT": sentiment_text,
        "CAPTION": caption or "Key US market development to watch.",
        "KEY_SIGNAL": signal,
        "TAKEAWAY": signal if signal != "No material figure reported" else clean(data.get("WHY_IT_MATTERS")) or clean(data.get("HOOK")) or "Investors are watching the next confirmed update.",
        "SOURCE": source,
        "HASHTAGS": clean(data.get("HASHTAGS")) or "#USStocks #StockMarket #MarketNews #WallStreet",
        "SOURCE_URL": source_url,
        "SLOT": slot,
        "IMAGE_URL": image_src,
        "LOGO_URL": "the-third-eye-logo.png",
    }

    logo_path = Path("assets/the-third-eye-logo.png")
    if logo_path.exists():
        (OUTPUT_DIR / logo_path.name).write_bytes(logo_path.read_bytes())

    # The HTML renderer performs the final text replacement in the browser.
    # Keep JSON separately so the Node renderer can inject escaped values safely.
    rendered = OUTPUT_DIR / "market_template.html"
    rendered.write_text(
        HTML_TEMPLATE_PATH.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    payload = OUTPUT_DIR / "market_template_data.json"
    payload.write_text(
        json.dumps(values, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return rendered, payload


# ============================================================
# HTML -> WEBM -> MP4
# ============================================================


def make_video(data, article, slot):
    print("Rendering HTML/CSS animated Shorts video...")
    html_path, data_path = render_html_template(data, article, slot)
    webm_path = OUTPUT_DIR / "_html_render.webm"
    final = OUTPUT_DIR / "us_market_news.mp4"

    # Node + Playwright capture the real browser animation at 1080x1920.
    subprocess.run(
        [
            "node",
            "scripts/render_html_video.js",
            str(html_path.resolve()),
            str(data_path.resolve()),
            str(webm_path.resolve()),
        ],
        check=True,
    )

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-i", str(webm_path),
            "-vf", f"scale={WIDTH}:{HEIGHT}:flags=lanczos,format=yuv420p",
            "-r", str(FPS),
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-movflags", "+faststart",
            "-an",
            str(final),
        ],
        check=True,
    )

    webm_path.unlink(missing_ok=True)
    print("7 HTML scenes rendered successfully.")
    print(f"Video ready: {final}")
    return final


# ============================================================
# YOUTUBE
# ============================================================

def upload(video_path, data, slot):
    credentials = Credentials(
        token=None,
        refresh_token=YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YOUTUBE_CLIENT_ID,
        client_secret=YOUTUBE_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )

    credentials.refresh(Request())
    youtube = build("youtube", "v3", credentials=credentials)

    title = clean(data.get("HEADLINE")) or "US Market News"
    title = f"{title} | US Market News #Shorts"[:100]

    description = f"""US MARKET NEWS — {slot}

{clean(data.get("HOOK"))}

WHAT HAPPENED:
{clean(data.get("WHAT_HAPPENED"))}

WHY IT MATTERS:
{clean(data.get("WHY_IT_MATTERS"))}

TICKERS:
{clean(data.get("TICKERS")) or "N/A"}

SENTIMENT:
{clean(data.get("SENTIMENT")) or "NEUTRAL"}

SOURCE:
{clean(data.get("SOURCE"))}

{clean(data.get("HASHTAGS"))}

News summary for informational purposes only. Not financial advice.
"""

    tags = [
        "US Market News", "US Stock Market", "Stocks",
        "Wall Street", "Market News", "US Stocks",
        "Finance", "Shorts"
    ]

    for t in ticker_list(data.get("TICKERS")):
        tags.append(t)

    body = {
        "snippet": {
            "title": title,
            "description": description[:5000],
            "tags": tags[:30],
            "categoryId": "25",
        },
        "status": {
            "privacyStatus": os.environ.get(
                "YOUTUBE_PRIVACY_STATUS", "private"
            ),
            "selfDeclaredMadeForKids": False,
        },
    }

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
        ),
    )

    response = request.execute()
    video_id = response["id"]

    print("=" * 60)
    print("YOUTUBE UPLOAD SUCCESS")
    print("https://www.youtube.com/watch?v=" + video_id)
    print("Privacy:", body["status"]["privacyStatus"])
    print("=" * 60)

    return video_id


# ============================================================
# MAIN
# ============================================================

def main():
    slot, now = slot_info()

    print("=" * 70)
    print("US MARKET NEWS V2")
    print("Slot:", slot)
    print("ET:", now.strftime("%Y-%m-%d %H:%M:%S %Z"))
    print("=" * 70)

    posted = load_state()
    articles = get_news()

    fresh = [
        a for a in articles
        if clean(a.get("url")) not in posted
    ]
    if fresh:
        articles = fresh

    raw_news = format_news(articles)
    raw = generate_content(raw_news, slot)
    data = parse_fields(raw)

    index = data.get("SELECTED_NEWS_INDEX", 1)
    if not 1 <= index <= len(articles):
        index = 1

    article = articles[index - 1]

    (OUTPUT_DIR / "market_news_raw.txt").write_text(raw, encoding="utf-8")
    (OUTPUT_DIR / "market_news_post.txt").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    video = make_video(data, article, slot)
    upload(video, data, slot)

    url = clean(article.get("url"))
    if url:
        posted.add(url)
        save_state(posted)

    print("Automation finished.")


if __name__ == "__main__":
    main()
