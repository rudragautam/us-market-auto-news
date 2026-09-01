import json
import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps
from google import genai
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

MARKETAUX_API_KEY = os.environ.get("MARKETAUX_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YOUTUBE_CLIENT_ID = os.environ.get("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = os.environ.get("YOUTUBE_CLIENT_SECRET")
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN")

OUTPUT_DIR = Path("output")
TEMPLATE_PATH = Path("templates/master.png")
STATE_PATH = Path("data/posted_news.json")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

WIDTH, HEIGHT = 1080, 1920
SLIDE_SECONDS = 5
ET = ZoneInfo("America/New_York")
TARGET_SLOTS = {(8, 30): "PRE-MARKET", (10, 0): "AFTER OPEN", (13, 0): "MID-MARKET", (16, 15): "AFTER CLOSE"}

missing = [k for k, v in {
    "MARKETAUX_API_KEY": MARKETAUX_API_KEY,
    "GEMINI_API_KEY": GEMINI_API_KEY,
    "YOUTUBE_CLIENT_ID": YOUTUBE_CLIENT_ID,
    "YOUTUBE_CLIENT_SECRET": YOUTUBE_CLIENT_SECRET,
    "YOUTUBE_REFRESH_TOKEN": YOUTUBE_REFRESH_TOKEN,
}.items() if not v]
if missing:
    raise RuntimeError("Missing GitHub secrets: " + ", ".join(missing))
if not TEMPLATE_PATH.exists():
    raise RuntimeError(f"Missing static template: {TEMPLATE_PATH}")


def clean(value):
    return re.sub(r"\s+", " ", str(value or "").replace("\x00", " ")).strip()


def get_slot():
    now = datetime.now(ET)
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch":
        return "MANUAL TEST", now
    best, best_diff = None, 10**9
    for (h, m), name in TARGET_SLOTS.items():
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        diff = abs((now - target).total_seconds())
        if diff < best_diff:
            best, best_diff = name, diff
    if best_diff > 600:
        print("Scheduled run is outside a target slot; exiting.")
        raise SystemExit(0)
    return best, now


def load_posted():
    if not STATE_PATH.exists():
        return set()
    try:
        return set(json.loads(STATE_PATH.read_text(encoding="utf-8")).get("urls", []))
    except Exception:
        return set()


def save_posted(urls):
    STATE_PATH.write_text(json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(), "urls": sorted(urls)[-500:]}, indent=2), encoding="utf-8")


def font(size, bold=False):
    candidates = []
    if os.name == "nt":
        candidates = [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\segoeuib.ttf"] if bold else [r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\segoeui.ttf"]
    else:
        candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"] if bold else ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for p in candidates:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def wrap(draw, text, fnt, max_width):
    words = clean(text).split()
    lines, cur = [], ""
    for word in words:
        test = word if not cur else cur + " " + word
        if draw.textbbox((0, 0), test, font=fnt)[2] <= max_width:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def fit_title(draw, text, max_width):
    for size in range(78, 43, -2):
        f = font(size, True)
        if draw.textbbox((0, 0), clean(text), font=f)[2] <= max_width:
            return f
    return font(44, True)


def draw_body(draw, text, x, y, max_width, fnt, fill=(230, 238, 248, 255), spacing=18):
    lh = fnt.getbbox("Ag")[3] - fnt.getbbox("Ag")[1]
    for line in wrap(draw, text, fnt, max_width):
        draw.text((x, y), line, font=fnt, fill=fill)
        y += lh + spacing
    return y


def fetch_news():
    url = "https://api.marketaux.com/v1/news/all"
    after = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
    params = {"api_token": MARKETAUX_API_KEY, "countries": "us", "language": "en", "filter_entities": "true", "must_have_entities": "true", "limit": 3, "group_similar": "true", "published_after": after}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    articles = r.json().get("data", [])
    if not articles:
        params.pop("published_after", None)
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        articles = r.json().get("data", [])
    if not articles:
        raise RuntimeError("No US market news returned by Marketaux")
    return articles


def news_text(articles):
    blocks = []
    for i, a in enumerate(articles, 1):
        entities = []
        for e in a.get("entities", []):
            n, s = clean(e.get("name")), clean(e.get("symbol"))
            if n or s:
                entities.append(f"{n or 'Unknown'} ({s or 'N/A'})")
        blocks.append(f"NEWS {i}\nTITLE:\n{clean(a.get('title'))}\n\nDESCRIPTION:\n{clean(a.get('description'))}\n\nSOURCE:\n{clean(a.get('source'))}\n\nPUBLISHED:\n{clean(a.get('published_at'))}\n\nENTITIES:\n{', '.join(entities)}\n\nURL:\n{clean(a.get('url'))}")
    return "\n\n" + ("\n\n" + "=" * 60 + "\n\n").join(blocks)


def generate_post(text, slot):
    client = genai.Client(api_key=GEMINI_API_KEY)
    prompt = f"""You are a professional US stock-market news editor.\nPOST SLOT: {slot}\n\nSelect ONE strongest, relevant US stock-market story from the supplied REAL Marketaux data. Use ONLY supplied facts. Never invent prices, percentages, earnings, revenue, dates, statements or guidance. Do not combine unrelated stories. Do not give financial advice. Avoid crypto-only stories unless the supplied story clearly has material US-equity impact. Tickers must come only from the selected story.\n\nReturn EXACTLY:\nSELECTED_NEWS_INDEX:\n<number>\n\nHEADLINE:\n<short factual headline>\n\nHOOK:\n<one engaging sentence>\n\nWHAT_HAPPENED:\n<2-3 concise sentences>\n\nWHY_IT_MATTERS:\n<2-3 concise sentences, no financial advice>\n\nTICKERS:\n<ticker list or N/A>\n\nSENTIMENT:\n<BULLISH / BEARISH / MIXED / NEUTRAL>\n\nCAPTION:\n<short caption>\n\nHASHTAGS:\n<8-12 relevant hashtags>\n\nSOURCE:\n<source name>\n\nNEWS DATA:\n{text}"""
    out = client.interactions.create(model="gemini-3.6-flash", input=prompt, store=False).output_text
    if not out:
        raise RuntimeError("Gemini returned empty output")
    return out.strip()


def parse(text):
    fields = ["SELECTED_NEWS_INDEX", "HEADLINE", "HOOK", "WHAT_HAPPENED", "WHY_IT_MATTERS", "TICKERS", "SENTIMENT", "CAPTION", "HASHTAGS", "SOURCE"]
    result = {}
    for i, field_name in enumerate(fields):
        nxt = fields[i + 1:]
        look = "|".join(re.escape(x) for x in nxt)
        pattern = rf"(?is)^\s*{re.escape(field_name)}:\s*(.*?)(?=^\s*(?:{look}):|\Z)" if look else rf"(?is)^\s*{re.escape(field_name)}:\s*(.*?)\Z"
        m = re.search(pattern, text, re.MULTILINE)
        result[field_name] = clean(m.group(1)) if m else ""
    try:
        result["SELECTED_NEWS_INDEX"] = int(re.search(r"\d+", result.get("SELECTED_NEWS_INDEX", "1")).group())
    except Exception:
        result["SELECTED_NEWS_INDEX"] = 1
    return result


def render_slide(base, number, section, title, body, footer):
    img = ImageOps.fit(base.copy(), (WIDTH, HEIGHT), method=Image.Resampling.LANCZOS).convert("RGBA")
    img = Image.alpha_composite(img, Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 55)))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((55, 245, WIDTH - 55, HEIGHT - 210), radius=36, fill=(4, 14, 30, 205), outline=(90, 160, 230, 110), width=2)
    d.text((75, 80), "US MARKET NEWS", font=font(34, True), fill=(235, 245, 255, 255))
    counter = f"{number:02d}/07"
    cf = font(30, True)
    cb = d.textbbox((0, 0), counter, font=cf)
    d.text((WIDTH - 75 - (cb[2] - cb[0]), 80), counter, font=cf, fill=(180, 215, 245, 230))
    d.text((90, 310), section.upper(), font=font(30, True), fill=(90, 190, 255, 255))
    tf = fit_title(d, title, WIDTH - 180)
    y = draw_body(d, title, 90, 385, WIDTH - 180, tf, (255, 255, 255, 255), 16) + 45
    if body:
        draw_body(d, body, 90, y, WIDTH - 180, font(42), (230, 238, 248, 255), 18)
    d.text((90, HEIGHT - 150), footer, font=font(28, True), fill=(175, 205, 230, 235))
    return img.convert("RGB")


def create_slides(parsed, article, slot):
    base = Image.open(TEMPLATE_PATH).convert("RGB")
    tickers = parsed.get("TICKERS") or "N/A"
    why = parsed.get("WHY_IT_MATTERS") or "Based only on the supplied news story."
    slides = [
        ("HEADLINE", parsed.get("HEADLINE") or "US Market Update", f"{tickers}  •  {parsed.get('SENTIMENT') or 'NEUTRAL'}"),
        ("THE HOOK", parsed.get("HOOK") or parsed.get("HEADLINE") or "US Market Update", f"{slot}  •  US EQUITIES"),
        ("WHAT HAPPENED", "What changed in the market?", parsed.get("WHAT_HAPPENED") or "No additional detail supplied."),
        ("WHY IT MATTERS", "Why investors are watching", why),
        ("STOCKS TO WATCH", tickers, "Tickers mentioned in the selected story only."),
        ("MARKET TAKEAWAY", parsed.get("SENTIMENT") or "NEUTRAL", why),
        ("SOURCE", parsed.get("SOURCE") or "Marketaux", clean(article.get("url")) or "Source URL unavailable"),
    ]
    for i, (section, title, body) in enumerate(slides, 1):
        slide = render_slide(base, i, section, title, body, "THE THIRD EYE  •  NEWS, NOT FINANCIAL ADVICE")
        slide.save(OUTPUT_DIR / f"slide_{i:02d}.png")


def create_video():
    path = OUTPUT_DIR / "us_market_news.mp4"
    cmd = ["ffmpeg", "-y", "-framerate", f"1/{SLIDE_SECONDS}", "-start_number", "1", "-i", str(OUTPUT_DIR / "slide_%02d.png"), "-c:v", "libx264", "-preset", "veryfast", "-r", "30", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(path)]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if r.returncode:
        print(r.stdout[-5000:])
        raise RuntimeError("FFmpeg failed")
    return path


def upload_youtube(video_path, parsed, slot):
    creds = Credentials(token=None, refresh_token=YOUTUBE_REFRESH_TOKEN, token_uri="https://oauth2.googleapis.com/token", client_id=YOUTUBE_CLIENT_ID, client_secret=YOUTUBE_CLIENT_SECRET, scopes=["https://www.googleapis.com/auth/youtube.upload"])
    creds.refresh(Request())
    youtube = build("youtube", "v3", credentials=creds)
    headline = clean(parsed.get("HEADLINE") or "US Market News")
    title = (headline + " | US Market News #Shorts")[:100]
    description = f"""US Market News — {slot}\n\n{parsed.get('HOOK', '')}\n\nWHAT HAPPENED:\n{parsed.get('WHAT_HAPPENED', '')}\n\nWHY IT MATTERS:\n{parsed.get('WHY_IT_MATTERS', '')}\n\nTICKERS:\n{parsed.get('TICKERS', 'N/A')}\n\nSENTIMENT:\n{parsed.get('SENTIMENT', 'NEUTRAL')}\n\nSOURCE:\n{parsed.get('SOURCE', 'Marketaux')}\n\n{parsed.get('HASHTAGS', '')}\n\nNews summary generated from supplied Marketaux data. Informational only; not financial advice."""[:5000]
    tags = ["US Stock Market", "US Market News", "Stock Market", "Stocks", "Market News", "US Stocks", "Wall Street", "Finance"]
    tags += [x for x in re.findall(r"\b[A-Z]{1,6}\b", parsed.get("TICKERS", "")) if x not in tags]
    privacy = os.environ.get("YOUTUBE_PRIVACY_STATUS", "private")
    if privacy not in {"private", "unlisted", "public"}:
        privacy = "private"
    body = {"snippet": {"title": title, "description": description, "tags": tags[:30], "categoryId": "25"}, "status": {"privacyStatus": privacy, "selfDeclaredMadeForKids": False}}
    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    response = youtube.videos().insert(part="snippet,status", body=body, media_body=media).execute()
    print("YOUTUBE UPLOAD SUCCESSFUL")
    print("Video ID:", response["id"])
    print("URL:", f"https://www.youtube.com/watch?v={response['id']}")
    print("Privacy:", privacy)
    return response["id"]


def main():
    slot, now = get_slot()
    print(f"US MARKET NEWS AUTOMATION | {slot} | {now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    posted = load_posted()
    articles = fetch_news()
    fresh = [a for a in articles if clean(a.get("url")) not in posted]
    if fresh:
        articles = fresh
    raw = generate_post(news_text(articles), slot)
    parsed = parse(raw)
    idx = parsed.get("SELECTED_NEWS_INDEX", 1)
    if not 1 <= idx <= len(articles):
        idx = 1
    article = articles[idx - 1]
    (OUTPUT_DIR / "market_news_post.txt").write_text(raw, encoding="utf-8")
    (OUTPUT_DIR / "source_url.txt").write_text(clean(article.get("url")), encoding="utf-8")
    create_slides(parsed, article, slot)
    video = create_video()
    upload_youtube(video, parsed, slot)
    if clean(article.get("url")):
        posted.add(clean(article.get("url")))
        save_posted(posted)
    print("Automation completed successfully.")


if __name__ == "__main__":
    main()
