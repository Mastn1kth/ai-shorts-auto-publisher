"""Local web interface contract tests."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app


class WebAppTests(unittest.TestCase):
    def setUp(self):
        self.client = web_app.app.test_client()
        web_app._jobs.clear()
        web_app._active_job = None

    def _post(self, **fields):
        form = {
            "csrf_token": web_app.CSRF_TOKEN,
            "video": (io.BytesIO(b"\x00\x00\x00\x18ftypisom"), "video.mp4"),
            "provider": "openai",
            "model": "test-model",
            "api_key": "private-key",
            "num_clips": "1",
            "privacy": "private",
        }
        form.update(fields)
        return self.client.post("/api/jobs", data=form, content_type="multipart/form-data")

    def test_rejects_bad_mp4_and_missing_csrf(self):
        bad_video = self._post(video=(io.BytesIO(b"not-a-video"), "video.mp4"))
        self.assertEqual(bad_video.status_code, 400)
        self.assertIn("MP4", bad_video.get_json()["error"])
        csrf = self._post(csrf_token="wrong")
        self.assertEqual(csrf.status_code, 403)

    def test_starts_local_job_without_exposing_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                with patch.object(web_app, "Thread") as thread:
                    response = self._post()
                    self.assertEqual(response.status_code, 202)
                    job_id = response.get_json()["id"]
                    self.assertTrue((Path(directory) / job_id / "source.mp4").is_file())
                    data = self.client.get(f"/api/jobs/{job_id}").get_json()
                    self.assertEqual(data["status"], "queued")
                    self.assertNotIn("private-key", str(data))
                    args = thread.call_args.kwargs["args"]
                    self.assertEqual(args[1]["api_key"], "private-key")

    def test_custom_api_rejects_non_https_remote_url(self):
        response = self._post(provider="custom", base_url="http://example.com/v1")
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
