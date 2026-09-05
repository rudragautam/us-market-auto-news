"""Focused fixtures for the payload consumed by the browser renderer."""
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("MARKETAUX_API_KEY", "test")
os.environ.setdefault("GEMINI_API_KEY", "test")
os.environ.setdefault("YOUTUBE_CLIENT_ID", "test")
os.environ.setdefault("YOUTUBE_CLIENT_SECRET", "test")
os.environ.setdefault("YOUTUBE_REFRESH_TOKEN", "test")

import main  # noqa: E402


ARTICLE = {
    "title": "Company reports a market development",
    "description": "A source-backed update is drawing investor attention.",
    "source": "Fixture Wire",
    "url": "https://example.test/story",
    "entities": [{"name": "Example Corp", "symbol": "EXM"}],
}


def story(tickers, headline="Company reports a market development"):
    return {
        "HEADLINE": headline,
        "HOOK": "A source-backed update is drawing investor attention.",
        "WHAT_HAPPENED": "First confirmed detail\nSecond confirmed detail\nThird confirmed detail",
        "WHY_IT_MATTERS": "Investors are monitoring the next update",
        "TICKERS": tickers,
        "KEY_SIGNAL": "No material figure reported",
        "SENTIMENT": "NEUTRAL",
        "CAPTION": "A factual summary for investors.",
        "HASHTAGS": "#USStocks #MarketNews",
        "SOURCE": "Fixture Wire",
    }


class RenderDataTests(unittest.TestCase):
    def render(self, tickers, **kwargs):
        main.render_html_template(story(tickers, **kwargs), ARTICLE, "MANUAL TEST")
        return json.loads((Path("output") / "market_template_data.json").read_text())

    def test_dynamic_ticker_counts(self):
        for tickers, expected in (("DELL", ["DELL"]), ("DELL, NVDA", ["DELL", "NVDA"]),
                                  ("DELL, NVDA, AMD, MSFT", ["DELL", "NVDA", "AMD", "MSFT"]),
                                  ("NONE", [])):
            with self.subTest(tickers=tickers):
                payload = self.render(tickers)
                self.assertEqual(payload["TICKERS"], expected)
                self.assertNotIn("STORY DRIVER", json.dumps(payload))

    def test_headline_lengths_do_not_create_placeholder_payloads(self):
        for headline in ("Brief update", "A deliberately long factual headline that should wrap safely on a vertical market-news video"):
            with self.subTest(headline=headline):
                payload = self.render("EXM", headline=headline)
                self.assertEqual(payload["HEADLINE"], headline)
                self.assertNotRegex(json.dumps(payload), r"\{\{|undefined|null|N/A|—")

    def test_missing_and_failed_images_use_fallback(self):
        payload = self.render("EXM")
        self.assertEqual(payload["IMAGE_URL"], "fallback-market.jpg")

        failed = dict(ARTICLE, image_url="http://127.0.0.1:9/not-an-image.jpg")
        with patch.object(main.requests, "get", side_effect=OSError("offline")):
            main.render_html_template(story("EXM"), failed, "MANUAL TEST")
        payload = json.loads((Path("output") / "market_template_data.json").read_text())
        self.assertEqual(payload["IMAGE_URL"], "fallback-market.jpg")

    def test_valid_download_is_used_after_image_validation(self):
        response = Mock(content=Path("assets/fallback-market.jpg").read_bytes(), headers={"content-type": "image/jpeg"})
        response.raise_for_status.return_value = None
        article = dict(ARTICLE, image_url="https://example.test/image.jpg")
        with patch.object(main.requests, "get", return_value=response):
            main.render_html_template(story("EXM"), article, "MANUAL TEST")
        payload = json.loads((Path("output") / "market_template_data.json").read_text())
        self.assertEqual(payload["IMAGE_URL"], "news_image.jpg")
        self.assertTrue((Path("output") / "news_image.jpg").exists())


if __name__ == "__main__":
    unittest.main()
