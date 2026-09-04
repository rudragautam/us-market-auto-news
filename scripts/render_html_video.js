const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const [htmlPath, dataPath, webmPath] = process.argv.slice(2);
  if (!htmlPath || !dataPath || !webmPath) {
    console.error('Usage: node render_html_video.js <html> <data.json> <output.webm>');
    process.exit(1);
  }

  const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  const html = fs.readFileSync(htmlPath, 'utf8');
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1080, height: 1920 },
    deviceScaleFactor: 1,
    recordVideo: { dir: path.dirname(webmPath), size: { width: 1080, height: 1920 } }
  });
  const page = await context.newPage();
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });

  await page.evaluate((d) => {
    document.body.classList.add('render-mode');
    const values = {
      HEADLINE: d.headline || 'US Market Update',
      HOOK: d.hook || '',
      WHAT_1: d.what?.[0] || '', WHAT_2: d.what?.[1] || '', WHAT_3: d.what?.[2] || '',
      WHY_1: d.why?.[0] || '', WHY_2: d.why?.[1] || '', WHY_3: d.why?.[2] || '',
      TICKER_1: d.tickers?.[0] ? '$' + d.tickers[0] : 'N/A',
      TICKER_2: d.tickers?.[1] ? '$' + d.tickers[1] : '—',
      TICKER_3: d.tickers?.[2] ? '$' + d.tickers[2] : '—',
      TICKER_4: d.tickers?.[3] ? '$' + d.tickers[3] : '—',
      MOVE_1: d.ticker_moves?.[0] || 'WATCH', MOVE_2: d.ticker_moves?.[1] || 'WATCH',
      MOVE_3: d.ticker_moves?.[2] || 'WATCH', MOVE_4: d.ticker_moves?.[3] || 'WATCH',
      SENTIMENT: d.sentiment || 'NEUTRAL', SENTIMENT_TEXT: d.sentiment_text || '',
      CAPTION: d.caption || '', KEY_SIGNAL: d.key_signal || 'N/A',
      TAKEAWAY: d.takeaway || '', SOURCE: d.source || 'Marketaux',
      HASHTAGS: d.hashtags || '', SOURCE_URL: d.source_url || '', SLOT: d.slot || 'MARKET UPDATE',
      IMAGE_URL: d.IMAGE_URL || d.image_url || ''
    };
    const replace = (root) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes=[]; while(walker.nextNode()) nodes.push(walker.currentNode);
      for (const node of nodes) {
        let text=node.nodeValue;
        for (const [k,v] of Object.entries(values)) text=text.split('{{'+k+'}}').join(String(v));
        node.nodeValue=text;
      }
    };
    replace(document.body);

    // Image slot: the HTML keeps a real Marketaux image as a preview fallback.
    // During automation, main.py supplies the downloaded local image path.
    for (const el of document.querySelectorAll('[data-image-slot]')) {
      const key = el.getAttribute('data-image-slot');
      if (key && values[key]) el.setAttribute('src', String(values[key]));
    }

    for (const el of document.querySelectorAll('[src], [href]')) {
      for (const attr of ['src', 'href']) {
        if (!el.hasAttribute(attr)) continue;
        let value = el.getAttribute(attr);
        for (const [k,v] of Object.entries(values)) value=value.split('{{'+k+'}}').join(String(v));
        el.setAttribute(attr, value);
      }
    }
  }, data);

  await page.waitForFunction(() => window.__THE_THIRD_EYE_READY__ === true);
  await page.waitForTimeout(34700);
  const videoPath = await page.video().path();
  await context.close();
  await browser.close();
  fs.copyFileSync(videoPath, webmPath);
  console.log(`HTML video captured: ${webmPath}`);
}

main().catch(err => { console.error(err); process.exit(1); });
