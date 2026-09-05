"""Focused fixtures for the payload consumed by the browser renderer."""
import json
import os
import subprocess
import tempfile
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

    def test_missing_background_audio_keeps_video(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "rendered.mp4"
            video.write_bytes(b"original")
            result = main.add_background_audio(video, Path(directory) / "missing.mp4")
            self.assertEqual(result, video)
            self.assertEqual(video.read_bytes(), b"original")

    def test_background_audio_loops_trims_and_replaces_safely(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "rendered.mp4"
            audio = Path(directory) / "music.mp4"
            video.write_bytes(b"original")
            audio.write_bytes(b"audio")

            def ffmpeg_success(command, **_kwargs):
                Path(command[-1]).write_bytes(b"muxed")

            with patch.object(main, "media_duration", return_value=34.7), \
                 patch.object(main.subprocess, "run", side_effect=ffmpeg_success) as run:
                main.add_background_audio(video, audio)

            command = run.call_args.args[0]
            self.assertIn("-stream_loop", command)
            self.assertIn("-shortest", command)
            self.assertIn("-c:v", command)
            self.assertIn("copy", command)
            audio_filter = command[command.index("-filter_complex") + 1]
            self.assertIn("volume=0.20", audio_filter)
            self.assertIn("atrim=duration=34.700", audio_filter)
            self.assertIn("afade=t=out:st=33.950:d=0.750", audio_filter)
            self.assertEqual(video.read_bytes(), b"muxed")

    def test_background_audio_failure_keeps_original_video(self):
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "rendered.mp4"
            audio = Path(directory) / "music.mp4"
            video.write_bytes(b"original")
            audio.write_bytes(b"audio")
            with patch.object(main, "media_duration", return_value=10), \
                 patch.object(main.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "ffmpeg")):
                main.add_background_audio(video, audio)
            self.assertEqual(video.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
