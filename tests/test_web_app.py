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

    def test_accepts_youtube_url_without_upload(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                with patch.object(web_app, "Thread"):
                    response = self._post(video=None, source_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(web_app._jobs[response.get_json()["id"]]["source"], "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    def test_rejects_non_youtube_url(self):
        response = self._post(video=None, source_url="https://evil.example/video")
        self.assertEqual(response.status_code, 400)

    def test_schedule_defaults_to_one_hour_between_clips(self):
        due = web_app._schedule_times(3, 60, "")
        from datetime import datetime
        self.assertEqual((datetime.fromisoformat(due[1]) - datetime.fromisoformat(due[0])).total_seconds(), 3600)

    def test_generation_saves_descriptions_and_queue_without_api_key(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                job_id = "test-job"
                folder = Path(directory) / job_id
                folder.mkdir()
                video = folder / "short_01.mp4"
                video.write_bytes(b"fake")
                web_app._jobs[job_id] = {"id": job_id, "source": str(folder / "source.mp4"), "status": "queued", "shorts": []}
                settings = {
                    "provider": "openai", "model": "test", "api_key": "private-key", "base_url": "",
                    "num_clips": 1, "platforms": ["youtube"], "privacy": "private",
                    "dry_run": False, "interval_minutes": 60, "start_at": "",
                }
                result = {"shorts": [{"clip_url": str(video), "title": "Moment", "hook_sentence": "Hook", "virality_reason": "Why"}]}
                with patch.object(web_app, "make_llm", return_value=lambda _: ""):
                    with patch.object(web_app, "generate_shorts", return_value=result):
                        with patch.object(web_app, "_thumbnail", return_value=False):
                            with patch.object(web_app, "Thread"):
                                web_app._run_job(job_id, settings)
                job = web_app._jobs[job_id]
                self.assertEqual(job["status"], "completed")
                self.assertEqual(job["shorts"][0]["description"], "Hook\n\nWhy")
                self.assertEqual(job["shorts"][0]["publishing"]["youtube"]["status"], "scheduled")
                self.assertNotIn("private-key", (folder / "job.json").read_text(encoding="utf-8"))

    def test_publish_queue_updates_status(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                job_id = "test-job"
                (Path(directory) / job_id).mkdir()
                web_app._jobs[job_id] = {
                    "id": job_id, "source": "source", "status": "completed", "platforms": ["vk"],
                    "privacy": "public", "dry_run": False, "publish_state": "pending",
                    "raw_shorts": [{"clip_url": "clip.mp4"}],
                    "shorts": [{"scheduled_at": "2020-01-01T00:00:00+00:00", "publishing": {"vk": {"status": "scheduled"}}}],
                }
                with patch.object(web_app, "publish_shorts", return_value=[{"publishing": {"vk": {"status": "uploaded"}}}]):
                    web_app._publish_job(job_id)
                self.assertEqual(web_app._jobs[job_id]["shorts"][0]["publishing"]["vk"]["status"], "uploaded")
                self.assertEqual(web_app._jobs[job_id]["publish_state"], "finished")


if __name__ == "__main__":
    unittest.main()
