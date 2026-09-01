import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
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
TEMPLATE_PATH = Path("templates/master.png")
STATE_PATH = Path("data/posted_news.json")

WIDTH, HEIGHT = 1080, 1920
SLIDE_SECONDS = 5
FPS = 30
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
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
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
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("urls", []))
    except Exception:
        return set()


def save_state(urls):
    STATE_PATH.write_text(
        json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "urls": sorted(urls)[-500:]
        }, indent=2),
        encoding="utf-8"
    )


def font(size, bold=False):
    candidates = []
    if os.name == "nt":
        candidates = [
            r"C:\Windows\Fonts\arialbd.ttf" if bold else r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf" if bold else r"C:\Windows\Fonts\segoeui.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
        ]

    for f in candidates:
        if os.path.exists(f):
            return ImageFont.truetype(f, size)
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words = clean(text).split()
    lines, line = [], ""

    for word in words:
        test = word if not line else f"{line} {word}"
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word

    if line:
        lines.append(line)
    return lines


def draw_lines(draw, text, x, y, max_width, fnt, fill, gap=14, max_lines=None):
    lines = wrap(draw, text, fnt, max_width)
    if max_lines:
        lines = lines[:max_lines]

    line_h = fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += line_h + gap
    return y


def fit_font(draw, text, max_width, start, minimum, bold=True):
    for size in range(start, minimum - 1, -2):
        fnt = font(size, bold)
        if draw.textbbox((0, 0), clean(text), font=fnt)[2] <= max_width:
            return fnt
    return font(minimum, bold)


def bullet_list(text):
    parts = re.split(r"[\n•]+", str(text or ""))
    parts = [clean(x).lstrip("-").strip() for x in parts if clean(x)]
    return parts[:4]


def extract_metrics(text):
    # Only surfaces numbers that actually exist in supplied news.
    patterns = [
        r"\$\s?\d+(?:\.\d+)?(?:\s?(?:million|billion|trillion|M|B|T))?",
        r"\d+(?:\.\d+)?%",
        r"\b\d+(?:\.\d+)?x\b",
    ]
    found = []
    for pattern in patterns:
        found.extend(re.findall(pattern, text, flags=re.I))

    result = []
    for x in found:
        x = clean(x)
        if x not in result:
            result.append(x)
    return result[:3]


def ticker_list(text):
    values = []
    for item in re.split(r"[,|/]+", text or ""):
        item = clean(item).upper().replace("$", "")
        if re.fullmatch(r"[A-Z]{1,6}", item) and item not in values:
            values.append(item)
    return values[:6]


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

This is NOT a long article. It is a fast visual news Short.
Write very short, punchy, factual copy.

STRICT RULES:
- Use only facts present in the supplied news.
- Never invent numbers, targets, ratings, earnings, dates or quotes.
- Do not give financial advice.
- Prefer a company/equity catalyst over generic filler.
- Tickers only from the selected story.
- If no number is present, do not invent one.
- Avoid crypto-only stories unless the story clearly affects US equities.
- Each bullet must be short enough for a mobile screen.

Return EXACTLY these fields:

SELECTED_NEWS_INDEX:
<number>

HEADLINE:
<6-12 word factual headline>

HOOK:
<8-18 word attention-grabbing sentence>

WHAT_HAPPENED:
<3 short bullet lines, each max 12 words>

WHY_IT_MATTERS:
<3 short bullet lines, each max 12 words>

TICKERS:
<comma-separated tickers, or N/A>

KEY_SIGNAL:
<one short factual phrase using a supplied number if useful, otherwise N/A>

SENTIMENT:
<BULLISH / BEARISH / MIXED / NEUTRAL>

CAPTION:
<one short sentence>

HASHTAGS:
<8-12 hashtags>

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
# VISUAL RENDERING
# ============================================================

def make_base():
    if not TEMPLATE_PATH.exists():
        raise RuntimeError(f"Missing {TEMPLATE_PATH}")

    base = ImageOps.fit(
        Image.open(TEMPLATE_PATH).convert("RGB"),
        (WIDTH, HEIGHT),
        method=Image.Resampling.LANCZOS,
    )

    # Darkened copy for readable typography.
    dark = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 80))
    return Image.alpha_composite(base.convert("RGBA"), dark)


def add_header(draw, slot, number):
    draw.text(
        (65, 60),
        "THE THIRD EYE",
        font=font(32, True),
        fill=(255, 255, 255, 245),
    )

    draw.text(
        (65, 105),
        "US MARKET NEWS",
        font=font(24, True),
        fill=(170, 210, 245, 230),
    )

    counter = f"{number:02d} / 07"
    bbox = draw.textbbox((0, 0), counter, font=font(27, True))
    draw.text(
        (1015 - (bbox[2] - bbox[0]), 65),
        counter,
        font=font(27, True),
        fill=(220, 235, 250, 230),
    )

    # Slot pill.
    pill = slot.upper()
    pf = font(24, True)
    pw = draw.textbbox((0, 0), pill, font=pf)[2] + 34
    draw.rounded_rectangle(
        (65, 155, 65 + pw, 200),
        radius=22,
        fill=(10, 35, 65, 225),
        outline=(100, 190, 255, 180),
        width=2,
    )
    draw.text((82, 163), pill, font=pf, fill=(220, 240, 255, 255))


def add_panel(draw, y1=275, y2=1600):
    draw.rounded_rectangle(
        (50, y1, 1030, y2),
        radius=38,
        fill=(3, 12, 27, 218),
        outline=(120, 190, 245, 90),
        width=2,
    )


def add_footer(draw):
    draw.text(
        (65, 1800),
        "NEWS SUMMARY  •  NOT FINANCIAL ADVICE",
        font=font(25, True),
        fill=(205, 220, 235, 205),
    )


def render_slides(data, article, slot):
    base = make_base()

    headline = data.get("HEADLINE") or "US Market Update"
    hook = data.get("HOOK") or headline
    what = bullet_list(data.get("WHAT_HAPPENED"))
    why = bullet_list(data.get("WHY_IT_MATTERS"))
    tickers = ticker_list(data.get("TICKERS"))
    sentiment = data.get("SENTIMENT") or "NEUTRAL"
    signal = data.get("KEY_SIGNAL") or "N/A"
    source = data.get("SOURCE") or clean(article.get("source")) or "Marketaux"
    source_url = clean(article.get("url"))

    raw_numbers = " ".join([
        clean(article.get("title")),
        clean(article.get("description")),
        signal,
    ])
    metrics = extract_metrics(raw_numbers)

    slides = []

    # 1 — COVER
    slides.append({
        "type": "cover",
        "label": "BREAKING MARKET STORY",
        "title": headline,
        "body": hook,
        "tickers": tickers,
        "sentiment": sentiment,
    })

    # 2 — HOOK / SIGNAL
    slides.append({
        "type": "signal",
        "label": "THE SIGNAL",
        "title": signal if signal != "N/A" else "Why the market is watching",
        "body": hook,
        "metrics": metrics,
    })

    # 3 — WHAT HAPPENED
    slides.append({
        "type": "bullets",
        "label": "WHAT HAPPENED",
        "title": "The key facts",
        "bullets": what,
    })

    # 4 — WHY IT MATTERS
    slides.append({
        "type": "bullets",
        "label": "WHY IT MATTERS",
        "title": "What investors are watching",
        "bullets": why,
    })

    # 5 — STOCKS
    slides.append({
        "type": "stocks",
        "label": "STOCKS TO WATCH",
        "title": tickers[0] if tickers else "US EQUITIES",
        "tickers": tickers,
        "body": "Companies explicitly mentioned in the selected story.",
    })

    # 6 — TAKEAWAY
    slides.append({
        "type": "takeaway",
        "label": "MARKET TAKEAWAY",
        "title": sentiment,
        "body": signal if signal != "N/A" else hook,
        "tickers": tickers,
    })

    # 7 — SOURCE / CTA
    slides.append({
        "type": "source",
        "label": "SOURCE",
        "title": source,
        "body": "Follow for the next US market move.",
        "url": source_url,
    })

    for i, s in enumerate(slides, 1):
        img = base.copy()
        draw = ImageDraw.Draw(img)
        add_header(draw, slot, i)

        if s["type"] == "cover":
            add_panel(draw, 285, 1640)

            lf = font(28, True)
            draw.text((85, 335), s["label"], font=lf, fill=(95, 195, 255, 255))

            tf = fit_font(draw, s["title"], 900, 86, 48, True)
            y = draw_lines(draw, s["title"], 85, 410, 900, tf, (255,255,255,255), 18)

            draw_lines(
                draw, s["body"], 85, y + 70, 900,
                font(42, False), (210, 225, 240, 255), 16, 4
            )

            if s["tickers"]:
                x = 85
                y2 = 1370
                for t in s["tickers"]:
                    tw = draw.textbbox((0,0), f"${t}", font=font(34, True))[2] + 50
                    draw.rounded_rectangle(
                        (x, y2, x+tw, y2+62),
                        radius=28,
                        fill=(15, 60, 100, 230),
                        outline=(100, 200, 255, 160),
                        width=2
                    )
                    draw.text((x+25, y2+12), f"${t}", font=font(34, True), fill="white")
                    x += tw + 15

            draw.text(
                (85, 1510),
                s["sentiment"].upper(),
                font=font(40, True),
                fill=(255, 220, 120, 255),
            )

        elif s["type"] == "signal":
            add_panel(draw)
            draw.text((85, 335), s["label"], font=font(28, True), fill=(95,195,255,255))

            title = s["title"]
            tf = fit_font(draw, title, 900, 82, 48, True)
            draw_lines(draw, title, 85, 420, 900, tf, "white", 16, 3)

            y = 730
            for metric in s["metrics"][:3]:
                draw.rounded_rectangle(
                    (85, y, 995, y+150),
                    radius=28,
                    fill=(10, 32, 58, 235),
                    outline=(90, 170, 230, 120),
                    width=2,
                )
                draw.text((120, y+35), metric, font=font(65, True), fill=(255,255,255,255))
                y += 180

            draw_lines(
                draw, s["body"], 85, 1320, 900,
                font(38, False), (215,230,242,255), 16, 4
            )

        elif s["type"] == "bullets":
            add_panel(draw)
            draw.text((85, 335), s["label"], font=font(28, True), fill=(95,195,255,255))

            tf = fit_font(draw, s["title"], 900, 72, 48, True)
            draw_lines(draw, s["title"], 85, 420, 900, tf, "white", 15, 2)

            y = 700
            for bullet in s["bullets"][:3]:
                draw.ellipse((90, y+10, 112, y+32), fill=(90,190,255,255))
                y = draw_lines(
                    draw, bullet, 145, y, 820,
                    font(42, False), (230,238,247,255), 14, 2
                ) + 55

        elif s["type"] == "stocks":
            add_panel(draw)
            draw.text((85, 335), s["label"], font=font(28, True), fill=(95,195,255,255))

            big = s["title"]
            draw.text((85, 430), f"${big}", font=font(110, True), fill=(255,255,255,255))

            y = 620
            for t in s["tickers"][:5]:
                draw.rounded_rectangle(
                    (85, y, 995, y+115),
                    radius=26,
                    fill=(8, 29, 53, 235),
                    outline=(80, 165, 225, 110),
                    width=2,
                )
                draw.text((120, y+28), f"${t}", font=font(50, True), fill=(245,250,255,255))
                y += 145

            draw_lines(
                draw, s["body"], 85, 1390, 900,
                font(34, False), (200,220,235,255), 12, 3
            )

        elif s["type"] == "takeaway":
            add_panel(draw)
            draw.text((85, 335), s["label"], font=font(28, True), fill=(95,195,255,255))

            draw.text(
                (85, 470),
                s["title"].upper(),
                font=font(105, True),
                fill=(255, 220, 120, 255),
            )

            draw_lines(
                draw, s["body"], 85, 720, 900,
                font(48, False), (230,240,248,255), 18, 5
            )

            if s["tickers"]:
                draw.text(
                    (85, 1250),
                    "MENTIONED",
                    font=font(26, True),
                    fill=(150,190,220,255)
                )
                draw.text(
                    (85, 1310),
                    "  ".join(f"${x}" for x in s["tickers"]),
                    font=font(55, True),
                    fill=(255,255,255,255)
                )

        elif s["type"] == "source":
            add_panel(draw)
            draw.text((85, 335), s["label"], font=font(28, True), fill=(95,195,255,255))

            tf = fit_font(draw, s["title"], 900, 76, 46, True)
            draw_lines(draw, s["title"], 85, 450, 900, tf, "white", 16, 3)

            draw_lines(
                draw, s["body"], 85, 780, 900,
                font(45, False), (220,235,245,255), 16, 3
            )

            if s["url"]:
                draw.rounded_rectangle(
                    (85, 1030, 995, 1260),
                    radius=28,
                    fill=(8, 25, 45, 240),
                    outline=(80,165,225,100),
                    width=2,
                )
                draw_lines(
                    draw, s["url"], 120, 1080, 840,
                    font(30, False), (180,210,235,255), 12, 5
                )

            draw.text(
                (85, 1390),
                "THE THIRD EYE",
                font=font(52, True),
                fill=(255,255,255,255)
            )

        add_footer(draw)

        path = OUTPUT_DIR / f"slide_{i:02d}.png"
        img.convert("RGB").save(path, quality=95)

    print("Created 7 redesigned slides.")


# ============================================================
# ANIMATED VIDEO
# ============================================================

def make_video():
    print("Rendering animated MP4...")

    clips = []

    for i in range(1, 8):
        inp = OUTPUT_DIR / f"slide_{i:02d}.png"
        clip = OUTPUT_DIR / f"_clip_{i:02d}.mp4"
        clips.append(clip)

        frames = SLIDE_SECONDS * FPS

        # Gentle Ken-Burns zoom; no extra image API required.
        vf = (
            f"zoompan=z='min(zoom+0.00055,1.06)':"
            f"d={frames}:"
            f"x='iw/2-(iw/zoom/2)':"
            f"y='ih/2-(ih/zoom/2)':"
            f"s={WIDTH}x{HEIGHT}:fps={FPS},"
            "format=yuv420p"
        )

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(inp),
            "-t", str(SLIDE_SECONDS),
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-pix_fmt", "yuv420p",
            "-an",
            str(clip),
        ]

        subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

    concat = OUTPUT_DIR / "_concat.txt"
    concat.write_text(
        "".join(f"file '{c.name}'\n" for c in clips),
        encoding="utf-8"
    )

    final = OUTPUT_DIR / "us_market_news.mp4"

    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat.name,
            "-c", "copy",
            "-movflags", "+faststart",
            final.name,
        ],
        cwd=OUTPUT_DIR,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    for c in clips:
        c.unlink(missing_ok=True)
    concat.unlink(missing_ok=True)

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

    render_slides(data, article, slot)
    video = make_video()
    upload(video, data, slot)

    url = clean(article.get("url"))
    if url:
        posted.add(url)
        save_state(posted)

    print("Automation finished.")


if __name__ == "__main__":
    main()
