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
  await page.setViewportSize({ width: 1080, height: 1920 });

  await page.evaluate((d) => {
    document.body.classList.add('render-mode');
    const values = {
      HEADLINE: d.HEADLINE || d.headline || 'US Market Update',
      HOOK: d.HOOK || d.hook || '',
      WHAT_1: d.WHAT_1 || d.what?.[0] || '', WHAT_2: d.WHAT_2 || d.what?.[1] || '', WHAT_3: d.WHAT_3 || d.what?.[2] || '',
      WHY_1: d.WHY_1 || d.why?.[0] || '', WHY_2: d.WHY_2 || d.why?.[1] || '', WHY_3: d.WHY_3 || d.why?.[2] || '',
      TICKER_1: d.TICKER_1 || (d.tickers?.[0] ? '$' + d.tickers[0] : 'N/A'),
      TICKER_2: d.TICKER_2 || (d.tickers?.[1] ? '$' + d.tickers[1] : '—'),
      TICKER_3: d.TICKER_3 || (d.tickers?.[2] ? '$' + d.tickers[2] : '—'),
      TICKER_4: d.TICKER_4 || (d.tickers?.[3] ? '$' + d.tickers[3] : '—'),
      MOVE_1: d.MOVE_1 || d.ticker_moves?.[0] || 'WATCH', MOVE_2: d.MOVE_2 || d.ticker_moves?.[1] || 'WATCH',
      MOVE_3: d.MOVE_3 || d.ticker_moves?.[2] || 'WATCH', MOVE_4: d.MOVE_4 || d.ticker_moves?.[3] || 'WATCH',
      SENTIMENT: d.SENTIMENT || d.sentiment || 'NEUTRAL', SENTIMENT_TEXT: d.SENTIMENT_TEXT || d.sentiment_text || '',
      CAPTION: d.CAPTION || d.caption || '', KEY_SIGNAL: d.KEY_SIGNAL || d.key_signal || 'N/A',
      TAKEAWAY: d.TAKEAWAY || d.takeaway || '', SOURCE: d.SOURCE || d.source || 'Marketaux',
      HASHTAGS: d.HASHTAGS || d.hashtags || '', SOURCE_URL: d.SOURCE_URL || d.source_url || '', SLOT: d.SLOT || d.slot || 'MARKET UPDATE'
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
    const unresolved = [...document.body.innerText.matchAll(/\{\{[A-Z0-9_]+\}\}/g)].map(m => m[0]);
    if (unresolved.length) throw new Error('Unresolved template placeholders: ' + [...new Set(unresolved)].join(', '));
  }, data);

  await page.waitForFunction(() => window.__THE_THIRD_EYE_READY__ === true);
  await page.waitForTimeout(35000);
  const videoPath = await page.video().path();
  await context.close();
  await browser.close();
  fs.copyFileSync(videoPath, webmPath);
  console.log(`HTML video captured: ${webmPath}`);
}

main().catch(err => { console.error(err); process.exit(1); });
