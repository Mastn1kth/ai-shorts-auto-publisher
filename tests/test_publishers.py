"""Contract tests for publishing without contacting social platforms."""

import os
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import Mock, patch

from shorts_generator.publishers.base import PublisherError
from shorts_generator.publishers.instagram import InstagramPublisher
from shorts_generator.publishers.service import publish_shorts, validate_publish_request
from shorts_generator.publishers.storage import public_video_url
from shorts_generator.publishers.vk import VKPublisher
from shorts_generator.pipeline import generate_shorts
import main as cli


class PublishRequestTests(unittest.TestCase):
    def test_unsafe_instagram_visibility_is_rejected_before_video_processing(self):
        with patch("shorts_generator.pipeline._run_local") as processing:
            with self.assertRaisesRegex(ValueError, "Instagram Reels require"):
                generate_shorts("input.mp4", mode="local", publish_platforms=["instagram"])
            processing.assert_not_called()

    def test_unlisted_vk_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "VK Video does not support"):
            validate_publish_request(["vk"], "unlisted")

    def test_failed_render_is_failed_publication(self):
        result = publish_shorts([{"clip_url": None, "error": "render failed"}], ["youtube", "vk"])
        self.assertEqual(result[0]["publishing"]["youtube"]["status"], "failed")
        self.assertEqual(result[0]["publishing"]["vk"]["error"], "render failed")

    @patch("shorts_generator.publishers.service.requests.get")
    def test_remote_dry_run_does_not_download(self, get):
        result = publish_shorts(
            [{"clip_url": "https://example.com/short.mp4", "title": "Test"}],
            ["youtube", "vk", "instagram"],
            dry_run=True,
        )
        get.assert_not_called()
        self.assertEqual(
            [item["status"] for item in result[0]["publishing"].values()],
            ["dry_run", "dry_run", "dry_run"],
        )


class InstagramTests(unittest.TestCase):
    @patch("shorts_generator.publishers.instagram.requests.get")
    @patch("shorts_generator.publishers.instagram.requests.post")
    def test_hosted_video_container_and_publish(self, post, get):
        post.side_effect = [
            Mock(**{"json.return_value": {"id": "container-1"}}),
            Mock(**{"json.return_value": {"id": "media-2"}}),
        ]
        get.return_value.json.return_value = {"status_code": "FINISHED"}
        publisher = InstagramPublisher(access_token="test-token", user_id="123")
        result = publisher.publish(
            "https://example.com/short.mp4", {"caption": "Example"}, privacy_status="public"
        )
        self.assertEqual(result["external_id"], "media-2")
        self.assertEqual(post.call_count, 2)
        self.assertEqual(get.call_count, 1)
        self.assertEqual(post.call_args_list[0].kwargs["data"]["video_url"], "https://example.com/short.mp4")
        self.assertEqual(post.call_args_list[0].kwargs["headers"]["Authorization"], "Bearer test-token")
        self.assertNotIn("test-token", str(post.call_args_list[0].args))

    def test_local_clip_is_uploaded_to_storage(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "short.mp4")
            with open(path, "wb") as video:
                video.write(b"fake-mp4")
            client = Mock()
            fake_boto3 = types.SimpleNamespace(client=Mock(return_value=client))
            config = {"MEDIA_S3_BUCKET": "clips", "MEDIA_PUBLIC_BASE_URL": "https://cdn.example.com"}
            with patch.dict(os.environ, config), patch.dict(sys.modules, {"boto3": fake_boto3}):
                url = public_video_url(path)
            self.assertTrue(url.startswith("https://cdn.example.com/shorts/"))
            self.assertTrue(url.endswith(".mp4"))
            self.assertEqual(client.upload_file.call_args.args[0:2], (path, "clips"))

    def test_private_reel_is_rejected(self):
        publisher = InstagramPublisher(access_token="test-token", user_id="123")
        with self.assertRaises(PublisherError):
            publisher.publish("https://example.com/short.mp4", {}, privacy_status="private")


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
