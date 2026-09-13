import json, os, re, subprocess, html
from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import requests
from google import genai

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
DATA = ROOT / "data" / "crime_state.json"
TEMPLATE = ROOT / "templates" / "crime_files_16x9.html"
OUTPUT.mkdir(exist_ok=True, parents=True)
DATA.parent.mkdir(exist_ok=True, parents=True)

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

RSS_FEEDS = [
    ("DOJ", "https://www.justice.gov/news/rss"),
    ("FBI", "https://www.fbi.gov/feeds/fbi-news"),
]

def clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()

def load_state():
    if not DATA.exists():
        return {"urls": []}
    try:
        return json.loads(DATA.read_text(encoding="utf-8"))
    except Exception:
        return {"urls": []}

def save_state(state):
    DATA.write_text(json.dumps(state, indent=2), encoding="utf-8")

def fetch_feed(name, url):
    r=requests.get(url,timeout=30,headers={"User-Agent":"CrimeFiles/1.0"})
    r.raise_for_status()
    text=r.text
    items=[]
    for block in re.findall(r"<item>(.*?)</item>", text, re.S|re.I):
        def tag(t):
            m=re.search(rf"<{t}[^>]*>(.*?)</{t}>",block,re.S|re.I)
            return clean(html.unescape(re.sub("<.*?>"," ",m.group(1)))) if m else ""
        items.append({"source":name,"title":tag("title"),"description":tag("description"),
                      "url":tag("link"),"published":tag("pubDate")})
    return items

def get_candidates():
    items=[]
    for name,url in RSS_FEEDS:
        try:
            items.extend(fetch_feed(name,url))
        except Exception as e:
            print(f"{name} feed skipped: {e}")
    # newest first, no duplicate URLs
    seen=set(); out=[]
    for x in items:
        if x["url"] and x["url"] not in seen:
            seen.add(x["url"]); out.append(x)
    return out[:20]

def make_story(candidates):
    news="\n\n---\n\n".join(
        f"SOURCE: {x['source']}\nTITLE: {x['title']}\nDATE: {x['published']}\nDESCRIPTION: {x['description']}\nURL: {x['url']}"
        for x in candidates
    )
    prompt=f"""You are the writer for a premium US true-crime documentary YouTube channel.
Choose ONE case/news item from the supplied PRIMARY-SOURCE feed and create one coherent 8-10 minute narration.
Do not invent facts. If the source does not establish a detail, do not state it.
Clearly attribute allegations to prosecutors/police/court documents where appropriate.
Do not sensationalize victims or include graphic detail.
Return JSON only:
{{"title":"...","hook":"...","narration":"1000-1400 words","scenes":[{{"beat":"...","visual":"...","on_screen":"..."}}],"source_url":"...","source_name":"..."}}
The narration must read like one continuous story, not bullet points.
Use 10-14 scenes. Each scene beat must advance the story.
SOURCE MATERIAL:
{news}"""
    client=genai.Client(api_key=GEMINI_API_KEY)
    res=client.interactions.create(model="gemini-3.6-flash",input=prompt,store=False)
    text=getattr(res,"output_text","").strip()
    if not text: raise RuntimeError("Gemini returned no story")
    text=re.sub(r"^```json\s*|\s*```$","",text.strip(),flags=re.I)
    return json.loads(text)

def make_tts(text, path):
    # Free local test voice; production can swap in a higher-quality provider.
    subprocess.run(["espeak","-w",str(path),"-s","145","-v","en-us",text],check=True)

def render_html(story):
    payload=json.dumps(story,ensure_ascii=False).replace("</","<\\/")
    page=TEMPLATE.read_text(encoding="utf-8").replace("__STORY_JSON__",payload)
    p=OUTPUT/"crime_story.html"; p.write_text(page,encoding="utf-8"); return p

def build_video(html_path, voice_path):
    # Browser renderer is supplied separately; it converts each dynamic scene to frames.
    renderer=ROOT/"tools"/"render_crime.js"
    subprocess.run(["node",str(renderer),str(html_path),str(OUTPUT/"frames")],check=True)
    video=OUTPUT/"crime_visual.mp4"
    subprocess.run(["ffmpeg","-y","-framerate","30","-i",str(OUTPUT/"frames/%06d.png"),
                    "-c:v","libx264","-pix_fmt","yuv420p","-crf","20","-preset","veryfast",str(video)],check=True)
    final=OUTPUT/"crime_files_test.mp4"
    subprocess.run(["ffmpeg","-y","-i",str(video),"-i",str(voice_path),"-map","0:v:0","-map","1:a:0",
                    "-c:v","copy","-c:a","aac","-b:a","160k","-shortest",str(final)],check=True)
    return final

def main():
    state=load_state()
    candidates=get_candidates()
    fresh=[x for x in candidates if x["url"] not in set(state.get("urls",[]))]
    if not fresh: fresh=candidates
    if not fresh: raise RuntimeError("No crime source items available")
    story=make_story(fresh)
    html_path=render_html(story)
    voice=OUTPUT/"narration.wav"; make_tts(story["narration"],voice)
    final=build_video(html_path,voice)
    if story.get("source_url"):
        state.setdefault("urls",[]).append(story["source_url"])
        state["urls"]=state["urls"][-500:]
        save_state(state)
    print(final)

if __name__=="__main__":
    main()
