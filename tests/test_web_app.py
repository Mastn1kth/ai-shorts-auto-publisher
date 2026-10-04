"""Local web interface contract tests."""

import io
import os
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
        secret_patcher = patch.object(web_app, "get_secret", side_effect=lambda name: "private-key" if name == "OPENAI_API_KEY" else "")
        secret_patcher.start()
        self.addCleanup(secret_patcher.stop)

    def _post(self, **fields):
        form = {
            "csrf_token": web_app.CSRF_TOKEN,
            "video": (io.BytesIO(b"\x00\x00\x00\x18ftypisom"), "video.mp4"),
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

    def test_simple_desktop_page_has_key_settings_but_no_ai_picker(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn('name="OPENAI_API_KEY"', html)
        self.assertIn('name="GEMINI_API_KEY"', html)
        self.assertNotIn('name="provider"', html)
        self.assertNotIn('name="model"', html)
        icon = self.client.get("/favicon.ico")
        self.assertEqual(icon.status_code, 200)
        icon.close()

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

    def test_requires_configured_ai_key(self):
        with patch.object(web_app, "get_secret", return_value=""):
            response = self._post()
        self.assertEqual(response.status_code, 400)
        self.assertIn("API-ключ", response.get_json()["error"])

    def test_sequence_mode_does_not_require_ai_key(self):
        from werkzeug.datastructures import MultiDict
        with patch.object(web_app, "get_secret", return_value=""):
            settings = web_app._settings(MultiDict({"video_mode": "sequence", "part_duration": "60"}))
        self.assertIsNone(settings["api_key"])
        self.assertIsNone(settings["provider"])

    def test_sequence_job_never_initializes_llm(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                job_id = "sequence-job"
                folder = Path(directory) / job_id
                folder.mkdir()
                video = folder / "part_01.mp4"
                video.write_bytes(b"fake")
                web_app._jobs[job_id] = {"id": job_id, "source": str(folder / "source.mp4"), "status": "queued", "shorts": []}
                settings = {
                    "video_mode": "sequence", "part_duration": 60, "provider": None,
                    "model": None, "api_key": None, "platforms": [], "privacy": "private",
                    "dry_run": True, "interval_minutes": 60, "start_at": "",
                }
                result = {"shorts": [{"clip_url": str(video), "title": "Part 1"}]}
                with patch.object(web_app, "make_llm") as make_llm:
                    with patch.object(web_app, "build_sequential_parts", return_value=result) as build:
                        with patch.object(web_app, "enhance_clip", return_value={"enhanced": False}):
                            with patch.object(web_app, "_thumbnail", return_value=False):
                                web_app._run_job(job_id, settings)
                self.assertEqual(web_app._jobs[job_id]["status"], "completed")
                make_llm.assert_not_called()
                build.assert_called_once()

    def test_auto_selects_available_ai_key_without_form_choices(self):
        from werkzeug.datastructures import MultiDict
        with patch.object(web_app, "get_secret", side_effect=lambda name: "gemini-key" if name == "GEMINI_API_KEY" else ""):
            settings = web_app._settings(MultiDict({"num_clips": "1", "privacy": "private"}))
        self.assertEqual(settings["provider"], "gemini")
        self.assertEqual(settings["model"], "gemini-2.5-flash")

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

    def test_next_job_starts_one_hour_after_existing_queue(self):
        from datetime import datetime, timedelta
        due = (datetime.now().astimezone() + timedelta(hours=2)).isoformat()
        web_app._jobs["other"] = {
            "publish_state": "pending", "dry_run": False,
            "shorts": [{"scheduled_at": due}],
        }
        next_at = datetime.fromisoformat(web_app._queue_start(60, ""))
        self.assertEqual((next_at - datetime.fromisoformat(due)).total_seconds(), 3600)

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

    def test_connection_status_does_not_return_tokens(self):
        with patch.object(web_app, "get_secret", side_effect=lambda name: "private-key" if "TOKEN" in name else ""):
            response = self.client.get("/api/connections")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("private-key", response.get_data(as_text=True))

    def test_latest_job_is_available_after_queue_restore(self):
        self.assertIsNone(self.client.get("/api/jobs/latest").get_json()["id"])
        web_app._jobs["recent"] = {"id": "recent", "status": "completed"}
        self.assertEqual(self.client.get("/api/jobs/latest").get_json()["id"], "recent")

    def test_interrupted_generation_is_reported_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / "interrupted"
            folder.mkdir()
            (folder / "job.json").write_text('{"id":"interrupted","status":"running","shorts":[]}', encoding="utf-8")
            with patch.object(web_app, "JOBS_DIR", Path(directory)):
                web_app.restore_jobs()
            self.assertEqual(web_app._jobs["interrupted"]["status"], "failed")
            self.assertIn("прервана", (folder / "job.json").read_text(encoding="utf-8"))

    def test_saving_platform_tokens_requires_csrf_and_uses_keyring(self):
        denied = self.client.post("/api/connections/tokens", data={"VK_ACCESS_TOKEN": "secret"})
        self.assertEqual(denied.status_code, 403)
        with patch.object(web_app, "save_secret") as saved:
            response = self.client.post("/api/connections/tokens", data={
                "csrf_token": web_app.CSRF_TOKEN, "VK_ACCESS_TOKEN": "secret",
            })
        self.assertEqual(response.status_code, 200)
        saved.assert_called_once_with("VK_ACCESS_TOKEN", "secret")

    def test_saving_ai_token_uses_keyring(self):
        with patch.object(web_app, "save_secret") as saved:
            response = self.client.post("/api/connections/tokens", data={
                "csrf_token": web_app.CSRF_TOKEN, "GEMINI_API_KEY": "gemini-key",
            })
        self.assertEqual(response.status_code, 200)
        saved.assert_called_once_with("GEMINI_API_KEY", "gemini-key")

    def test_youtube_oauth_client_file_is_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            with patch.object(web_app, "UI_CREDENTIALS_DIR", folder):
                with patch.object(web_app, "YOUTUBE_CLIENT_FILE", folder / "client_secret.json"):
                    with patch.object(web_app, "YOUTUBE_TOKEN_FILE", folder / "youtube-token.json"):
                        with patch.dict(os.environ, {}, clear=False):
                            invalid = self.client.post("/api/connections/youtube/client", data={
                                "csrf_token": web_app.CSRF_TOKEN,
                                "client_file": (io.BytesIO(b"{}"), "client.json"),
                            })
                            self.assertEqual(invalid.status_code, 400)
                            valid = self.client.post("/api/connections/youtube/client", data={
                                "csrf_token": web_app.CSRF_TOKEN,
                                "client_file": (io.BytesIO(b'{"installed":{"client_id":"id","client_secret":"secret"}}'), "client.json"),
                            })
                            self.assertEqual(valid.status_code, 200)
                            self.assertTrue((folder / "client_secret.json").is_file())


if __name__ == "__main__":
    unittest.main()
