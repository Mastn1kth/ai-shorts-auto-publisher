"""Contract tests for publishing without contacting social platforms."""

import os
import requests
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from shorts_generator.publishers.base import PublisherError
from shorts_generator.publishers.ledger import PublishingLedger
from shorts_generator.publishers.service import publish_shorts, validate_publish_request
from shorts_generator.publishers.telegram import TelegramPublisher
from shorts_generator.publishers.vk import VKPublisher
from shorts_generator.pipeline import generate_shorts
import main as cli


class PublishRequestTests(unittest.TestCase):
    def test_unsupported_platform_is_rejected_before_video_processing(self):
        with patch("shorts_generator.pipeline._run_local") as processing:
            with self.assertRaisesRegex(ValueError, "Unsupported publishing platforms"):
                generate_shorts("input.mp4", mode="local", publish_platforms=["other"])
            processing.assert_not_called()

    def test_unlisted_vk_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "VK Video does not support"):
            validate_publish_request(["vk"], "unlisted")

    def test_telegram_requires_explicit_public_visibility(self):
        with self.assertRaisesRegex(ValueError, "Telegram publishing requires"):
            validate_publish_request(["telegram"], "private")
        self.assertEqual(validate_publish_request(["telegram"], "public"), ["telegram"])

    def test_failed_render_is_failed_publication(self):
        result = publish_shorts([{"clip_url": None, "error": "render failed"}], ["youtube", "vk"])
        self.assertEqual(result[0]["publishing"]["youtube"]["status"], "failed")
        self.assertEqual(result[0]["publishing"]["vk"]["error"], "render failed")

    @patch("shorts_generator.publishers.service.requests.get")
    def test_remote_dry_run_does_not_download(self, get):
        result = publish_shorts(
            [{"clip_url": "https://example.com/short.mp4", "title": "Test"}],
            ["youtube", "vk"],
            dry_run=True,
        )
        get.assert_not_called()
        self.assertEqual(
            [item["status"] for item in result[0]["publishing"].values()],
            ["dry_run", "dry_run"],
        )


class VKTests(unittest.TestCase):
    @patch("shorts_generator.publishers.vk.requests.post")
    def test_upload_error_is_failure(self, post):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "short.mp4")
            with open(path, "wb") as video:
                video.write(b"fake-mp4")
            post.side_effect = [
                Mock(**{"json.return_value": {"response": {"upload_url": "https://upload.example.com", "owner_id": 1, "video_id": 2}}}),
                Mock(content=b"{}", **{"json.return_value": {"error": {"error_msg": "upload rejected"}}}),
            ]
            with self.assertRaisesRegex(PublisherError, "upload rejected"):
                VKPublisher(access_token="test-token").publish(path, {"title": "Test"})
            self.assertEqual(post.call_args_list[0].kwargs["data"]["access_token"], "test-token")
            self.assertNotIn("test-token", str(post.call_args_list[0].args))


class TelegramTests(unittest.TestCase):
    @patch("shorts_generator.publishers.telegram.requests.post")
    def test_upload_returns_channel_link(self, post):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "short.mp4")
            with open(path, "wb") as video:
                video.write(b"fake-mp4")
            post.return_value.json.return_value = {"ok": True, "result": {"message_id": 42}}
            result = TelegramPublisher(bot_token="secret", chat_id="@mychannel").publish(
                path, {"caption": "Test"}, privacy_status="public"
            )
            self.assertEqual(result["url"], "https://t.me/mychannel/42")
            self.assertEqual(post.call_args.kwargs["data"]["chat_id"], "@mychannel")
            self.assertEqual(post.call_args.kwargs["files"]["video"][2], "video/mp4")

    @patch("shorts_generator.publishers.telegram.requests.post")
    def test_request_failure_does_not_leak_token(self, post):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "short.mp4")
            with open(path, "wb") as video:
                video.write(b"fake-mp4")
            post.side_effect = requests.RequestException("https://api.telegram.org/botsecret/sendVideo failed")
            with self.assertRaises(PublisherError) as raised:
                TelegramPublisher(bot_token="secret", chat_id="@mychannel").publish(
                    path, {"caption": "Test"}, privacy_status="public"
                )
            self.assertNotIn("secret", str(raised.exception))

    @patch("shorts_generator.publishers.telegram.requests.post")
    def test_large_video_is_rejected_before_request(self, post):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "short.mp4")
            with open(path, "wb") as video:
                video.truncate(50 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(PublisherError, "50 MB"):
                TelegramPublisher(bot_token="secret", chat_id="@mychannel").publish(
                    path, {"caption": "Test"}, privacy_status="public"
                )
            post.assert_not_called()


class LedgerTests(unittest.TestCase):
    def _clip(self, directory):
        path = os.path.join(directory, "clip.mp4")
        with open(path, "wb") as video:
            video.write(b"same video bytes")
        return {"clip_url": path, "title": "Test", "start_time": 1.0, "end_time": 5.0}

    def test_success_is_skipped_on_second_run_and_force_republishes(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = os.path.join(directory, "ledger.json")
            clip = self._clip(directory)
            publisher = Mock()
            publisher.publish.return_value = {"platform": "vk", "status": "uploaded", "external_id": "123"}
            with patch.dict(os.environ, {"PUBLISH_LEDGER_FILE": ledger_path, "VK_ACCESS_TOKEN": "secret"}):
                with patch("shorts_generator.publishers.service._publisher", return_value=publisher):
                    first = publish_shorts([clip], ["vk"])
                    second = publish_shorts([clip], ["vk"])
                    forced = publish_shorts([clip], ["vk"], force_republish=True)
            self.assertEqual(first[0]["publishing"]["vk"]["status"], "uploaded")
            self.assertEqual(second[0]["publishing"]["vk"]["status"], "already_uploaded")
            self.assertEqual(publisher.publish.call_count, 2)
            self.assertEqual(forced[0]["publishing"]["vk"]["status"], "uploaded")
            with open(ledger_path, encoding="utf-8") as ledger:
                self.assertNotIn("secret", ledger.read())

    def test_partial_failure_retries_only_failed_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = self._clip(directory)
            youtube = Mock()
            youtube.publish.return_value = {"platform": "youtube", "status": "uploaded", "external_id": "yt-1"}
            vk = Mock()
            vk.publish.side_effect = [RuntimeError("network error"), {"platform": "vk", "status": "uploaded"}]
            publishers = {"youtube": youtube, "vk": vk}
            with patch.dict(os.environ, {"PUBLISH_LEDGER_FILE": os.path.join(directory, "ledger.json")}):
                with patch("shorts_generator.publishers.service._publisher", side_effect=publishers.get):
                    first = publish_shorts([clip], ["youtube", "vk"])
                    second = publish_shorts([clip], ["youtube", "vk"])
            self.assertEqual(first[0]["publishing"]["vk"]["status"], "failed")
            self.assertEqual(second[0]["publishing"]["youtube"]["status"], "already_uploaded")
            self.assertEqual(second[0]["publishing"]["vk"]["status"], "uploaded")
            youtube.publish.assert_called_once()
            self.assertEqual(vk.publish.call_count, 2)

    def test_tracking_failure_preserves_successful_upload_result(self):
        with tempfile.TemporaryDirectory() as directory:
            clip = self._clip(directory)
            publisher = Mock()
            publisher.publish.return_value = {"platform": "vk", "status": "uploaded", "external_id": "123"}
            with patch.dict(os.environ, {"PUBLISH_LEDGER_FILE": os.path.join(directory, "ledger.json")}):
                with patch("shorts_generator.publishers.service._publisher", return_value=publisher):
                    with patch("shorts_generator.publishers.service.PublishingLedger.record", side_effect=OSError("disk full")):
                        result = publish_shorts([clip], ["vk"])
            status = result[0]["publishing"]["vk"]
            self.assertEqual(status["status"], "uploaded")
            self.assertIn("disk full", status["tracking_error"])

    @patch("shorts_generator.publishers.service.requests.get")
    def test_new_hosted_url_for_same_source_and_segment_is_skipped(self, get):
        with tempfile.TemporaryDirectory() as directory:
            publisher = Mock()
            publisher.publish.return_value = {"platform": "youtube", "status": "uploaded", "external_id": "yt-1"}
            get.return_value.iter_content.return_value = [b"fake-mp4"]
            first_clip = {"clip_url": "https://cdn.example.com/first.mp4", "start_time": 10.0, "end_time": 30.0}
            second_clip = {**first_clip, "clip_url": "https://cdn.example.com/second.mp4"}
            with patch.dict(os.environ, {"PUBLISH_LEDGER_FILE": os.path.join(directory, "ledger.json")}):
                with patch("shorts_generator.publishers.service._publisher", return_value=publisher):
                    first = publish_shorts([first_clip], ["youtube"], source_id="https://youtube.com/watch?v=1")
                    second = publish_shorts([second_clip], ["youtube"], source_id="https://youtube.com/watch?v=1")
            self.assertEqual(first[0]["publishing"]["youtube"]["status"], "uploaded")
            self.assertEqual(second[0]["publishing"]["youtube"]["status"], "already_uploaded")
            publisher.publish.assert_called_once()
            get.assert_called_once()

    def test_youtube_key_is_stable_when_oauth_file_appears(self):
        with tempfile.TemporaryDirectory() as directory:
            token_file = os.path.join(directory, "youtube-token.json")
            clip = self._clip(directory)
            ledger = PublishingLedger(path=os.path.join(directory, "ledger.json"))
            with patch.dict(os.environ, {"YOUTUBE_TOKEN_FILE": token_file, "YOUTUBE_ACCOUNT_ID": ""}):
                before = ledger.key("youtube", clip["clip_url"], clip, None)
                with open(token_file, "w", encoding="utf-8") as token:
                    token.write('{"refresh_token":"new-token"}')
                after = ledger.key("youtube", clip["clip_url"], clip, None)
            self.assertEqual(before, after)


class CLITests(unittest.TestCase):
    def test_failed_platform_returns_nonzero(self):
        generated = {
            "mode": "local", "source_video_url": "input.mp4", "highlights": [{}],
            "shorts": [{
                "score": 50, "start_time": 1.0, "end_time": 5.0,
                "title": "Test", "hook_sentence": "Test", "clip_url": "short.mp4",
                "publishing": {"vk": {"status": "failed", "error": "upload rejected"}},
            }],
        }
        with patch.object(sys, "argv", ["main.py", "input.mp4", "--mode", "local", "--publish", "vk"]):
            with patch.object(cli, "generate_shorts", return_value=generated):
                with redirect_stdout(StringIO()):
                    self.assertEqual(cli.main(), 2)


if __name__ == "__main__":
    unittest.main()
