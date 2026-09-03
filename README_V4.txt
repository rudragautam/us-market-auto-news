US Market Auto News — V4 HTML/Browser Video Renderer

WHAT CHANGED
1. main.py: REPLACE your existing main.py completely with this V4 version.
   - Pillow slide rendering is removed from the active video path.
   - HTML/CSS template is populated from Gemini output.
   - Playwright/Chromium captures the animated 1080x1920 browser video.
   - FFmpeg converts the browser recording to MP4.
   - YouTube upload/state tracking remain in the pipeline.

2. templates/market_template.html: NEW — copy/keep exactly as supplied.
   - This is the active THE THIRD EYE 9:16 template.

3. scripts/render_html_video.js: NEW.
   - Captures the HTML/CSS animation using Chromium at 1080x1920.

4. package.json: NEW.
   - Minimal Node project marker.

5. .github/workflows/market.yml: REPLACE the existing workflow with this V4 version.
   - Adds Node.js, Playwright and Chromium installation.
   - Existing Marketaux/Gemini/YouTube secrets are unchanged.

6. requirements.txt: REPLACE with V4 version.

7. templates/master.png can remain in the repo for now, but it is NO LONGER USED by the active renderer.

TESTING
- YouTube privacy remains controlled by YOUTUBE_PRIVACY_STATUS; current test setup is private.
- Run GitHub Actions manually first.
- Download the output artifact and inspect output/us_market_news.mp4.

VIDEO
- 1080x1920
- 9:16
- 30 FPS
- 7 scenes x ~5 seconds = ~35 seconds
- Browser CSS animations are preserved in the capture.
