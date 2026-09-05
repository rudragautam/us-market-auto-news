const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

async function main() {
  const htmlPath = process.argv[2];
  const dataPath = process.argv[3];
  const webmPath = process.argv[4];

  if (!htmlPath || !dataPath || !webmPath) {
    throw new Error('Usage: node render_html_video.js <html> <data.json> <output.webm>');
  }

  const data = JSON.parse(fs.readFileSync(dataPath, 'utf8'));
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1080, height: 1920 },
    deviceScaleFactor: 1,
    recordVideo: {
      dir: path.dirname(webmPath),
      size: { width: 1080, height: 1920 }
    }
  });

  const page = await context.newPage();
  await page.goto('file://' + path.resolve(htmlPath), { waitUntil: 'load' });

  await page.evaluate((d) => {
    document.body.classList.add('render-mode');

    const cleanText = (value, fallback = '') => {
      const text = String(value ?? '').replace(/\{\{[^}]+\}\}/g, '').trim();
      return /^(?:undefined|null|n\/?a|none|—|-)$/i.test(text) ? fallback : text;
    };

    const values = {
      HEADLINE: cleanText(d.HEADLINE || d.headline, 'Market development in focus'),
      HOOK: cleanText(d.HOOK || d.hook),
      WHAT_1: d.WHAT_1 || d.what?.[0] || '',
      WHAT_2: d.WHAT_2 || d.what?.[1] || '',
      WHAT_3: d.WHAT_3 || d.what?.[2] || '',
      WHY_1: d.WHY_1 || d.why?.[0] || '',
      WHY_2: d.WHY_2 || d.why?.[1] || '',
      WHY_3: d.WHY_3 || d.why?.[2] || '',
      SENTIMENT: d.SENTIMENT || d.sentiment || 'NEUTRAL',
      SENTIMENT_TEXT: d.SENTIMENT_TEXT || d.sentiment_text || 'Market tone remains mixed.',
      CAPTION: d.CAPTION || d.caption || '',
      KEY_SIGNAL: d.KEY_SIGNAL || d.key_signal || 'No material figure reported.',
      TAKEAWAY: d.TAKEAWAY || d.takeaway || 'Investors are watching the next confirmed update.',
      SOURCE: d.SOURCE || d.source || 'Marketaux',
      HASHTAGS: d.HASHTAGS || d.hashtags || '',
      SOURCE_URL: d.SOURCE_URL || d.source_url || '',
      SLOT: d.SLOT || d.slot || 'MARKET UPDATE',
      IMAGE_URL: cleanText(d.IMAGE_URL || d.image_url, 'fallback-market.jpg'),
      LOGO_URL: cleanText(d.LOGO_URL || d.logo_url, 'ms_logo.png')
    };
    Object.keys(values).forEach((key) => { values[key] = cleanText(values[key]); });
    values.IMAGE_URL ||= 'fallback-market.jpg';
    values.LOGO_URL ||= 'ms_logo.png';

    // Replace normal text placeholders.
    const replace = (root) => {
      const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
      const nodes = [];
      while (walker.nextNode()) nodes.push(walker.currentNode);
      for (const node of nodes) {
        let text = node.nodeValue;
        for (const [k, v] of Object.entries(values)) {
          text = text.split('{{' + k + '}}').join(String(v ?? ''));
        }
        node.nodeValue = text;
      }
    };
    replace(document.body);

    // Dynamic image from Marketaux/local output.
    for (const el of document.querySelectorAll('[data-image-slot]')) {
      const key = el.getAttribute('data-image-slot');
      if (key && values[key]) {
        el.onerror = () => {
          if (!el.src.endsWith('/fallback-market.jpg')) el.src = 'fallback-market.jpg';
        };
        el.setAttribute('src', String(values[key]));
      }
    }

    // Use the supplied brand mark wherever the compact CSS eye previously
    // appeared, keeping the logo subtle in headers and prominent at the end.
    document.querySelectorAll('.brand > .eye, .channel-strip > .eye').forEach((eye) => {
      const logo = document.createElement('img');
      logo.className = 'brand-logo';
      logo.src = values.LOGO_URL;
      logo.alt = 'MarketScope';
      logo.onerror = () => { logo.style.display = 'none'; };
      eye.replaceWith(logo);
    });

    // ------------------------------------------------------------
    // DYNAMIC TICKERS — only real values are rendered.
    // No "—", "-", "N/A", "NONE", or empty cards.
    // ------------------------------------------------------------
    const tickerGrid = document.querySelector('#ticker-grid');
    if (tickerGrid) {
      tickerGrid.innerHTML = '';

      const rawTickers = Array.isArray(d.tickers)
        ? d.tickers
        : Array.isArray(d.TICKERS)
          ? d.TICKERS
          : String(d.tickers || d.TICKERS || '').split(/[\n,•]+/);

      const drivers = Array.isArray(d.ticker_drivers)
        ? d.ticker_drivers
        : Array.isArray(d.TICKER_DRIVERS)
          ? d.TICKER_DRIVERS
          : Array.isArray(d.ticker_moves)
            ? d.ticker_moves
            : [];

      rawTickers
        .map((ticker, index) => {
          if (ticker === null || ticker === undefined) return null;

          const symbol = String(ticker).trim().replace(/^\$/, '').toUpperCase();
          if (!symbol) return null;

          const invalid = ['—', '-', 'N/A', 'NA', 'NONE', 'NULL'];
          if (invalid.includes(symbol.toUpperCase())) return null;

          let driver = drivers[index] == null ? '' : String(drivers[index]).trim();
          if (invalid.includes(driver.toUpperCase())) driver = '';

          return { symbol, driver };
        })
        .filter(Boolean)
        .slice(0, 4)
        .forEach((item, index) => {
          const card = document.createElement('div');
          card.className = 'card animate ' + (index < 2 ? 'd2' : 'd3');

          const ticker = document.createElement('div');
          ticker.className = 'ticker';
          ticker.textContent = item.symbol.startsWith('$') ? item.symbol : '$' + item.symbol;
          card.appendChild(ticker);

          if (item.driver) {
            const move = document.createElement('div');
            move.className = 'move';
            move.textContent = item.driver;
            card.appendChild(move);
          }

          tickerGrid.appendChild(card);
        });
    }

    // Replace placeholders in src/href attributes too.
    for (const el of document.querySelectorAll('[src], [href]')) {
      for (const attr of ['src', 'href']) {
        if (!el.hasAttribute(attr)) continue;
        let value = el.getAttribute(attr);
        for (const [k, v] of Object.entries(values)) {
          value = value.split('{{' + k + '}}').join(String(v ?? ''));
        }
        el.setAttribute(attr, value);
      }
    }

    window.__THE_THIRD_EYE_READY__ = true;
  }, data);

  await page.waitForFunction(() => window.__THE_THIRD_EYE_READY__ === true);
  await page.waitForTimeout(34700);

  const videoPath = await page.video().path();
  await context.close();
  await browser.close();

  fs.copyFileSync(videoPath, webmPath);
  console.log(`HTML video captured: ${webmPath}`);
}

main().catch(err => {
  console.error(err);
  process.exit(1);
});
