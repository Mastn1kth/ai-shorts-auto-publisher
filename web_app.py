"""Local-only web interface for MP4-to-shorts jobs."""

import os
import re
import secrets
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file

from shorts_generator import generate_shorts
from shorts_generator.local.llm import make_llm
from shorts_generator.local.downloader import _extract_youtube_video_id
from shorts_generator.publishers.service import validate_publish_request


ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "output" / "ui-jobs"
CSRF_TOKEN = secrets.token_urlsafe(32)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
PROVIDERS = {"openai", "gemini", "openrouter", "groq", "custom"}

app = Flask(__name__, template_folder="web/templates", static_folder="web/static")
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
_jobs = {}
_lock = Lock()
_active_job = None


def _safe_error(error: Exception, submitted_key: str) -> str:
    message = str(error)
    keys = [submitted_key] + [os.getenv(name, "") for name in (
        "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
        "VK_ACCESS_TOKEN", "TELEGRAM_BOT_TOKEN",
    )]
    for key in keys:
        if key:
            message = message.replace(key, "[hidden]")
    return message[:500] or type(error).__name__


def _settings(form):
    provider = form.get("provider", "").strip().lower()
    model = form.get("model", "").strip()
    api_key = form.get("api_key", "").strip()
    base_url = form.get("base_url", "").strip()
    if provider not in PROVIDERS:
        raise ValueError("Выберите поддерживаемый ИИ-сервис")
    if not model or len(model) > 120:
        raise ValueError("Укажите название модели (до 120 символов)")
    if len(api_key) > 4096:
        raise ValueError("API-ключ слишком длинный")
    if provider == "custom":
        parsed = urlparse(base_url)
        local_http = parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        if (parsed.scheme != "https" and not local_http) or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Для своего API укажите HTTPS-адрес или локальный http://127.0.0.1")
    else:
        base_url = ""
    try:
        num_clips = int(form.get("num_clips", "3"))
    except ValueError as exc:
        raise ValueError("Количество клипов должно быть числом") from exc
    if not 1 <= num_clips <= 10:
        raise ValueError("Можно создать от 1 до 10 клипов за запуск")
    privacy = form.get("privacy", "private")
    platforms = validate_publish_request(form.getlist("platforms"), privacy)
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": base_url,
        "num_clips": num_clips,
        "platforms": platforms,
        "privacy": privacy,
        "dry_run": form.get("dry_run") == "on",
    }


def _youtube_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in {
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "www.youtu.be"
    }:
        raise ValueError("Нужна HTTPS-ссылка на видео YouTube")
    video_id = _extract_youtube_video_id(value)
    if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Не удалось распознать ID видео YouTube")
    return value


def _run_job(job_id: str, settings: dict) -> None:
    global _active_job
    job = _jobs[job_id]
    job["status"] = "running"
    try:
        llm = make_llm(settings["provider"], settings["model"], settings["api_key"], settings["base_url"])
        result = generate_shorts(
            job["source"],
            mode="local",
            num_clips=settings["num_clips"],
            llm_fn=llm,
            output_dir=str(JOBS_DIR / job_id),
            publish_platforms=settings["platforms"],
            publish_privacy=settings["privacy"],
            publish_dry_run=settings["dry_run"],
        )
        job["shorts"] = [
            {
                "title": short.get("title"),
                "score": short.get("score"),
                "start_time": short.get("start_time"),
                "end_time": short.get("end_time"),
                "error": short.get("error"),
                "publishing": short.get("publishing") or {},
                "video_url": f"/api/jobs/{job_id}/clips/{index}" if short.get("clip_url") else None,
            }
            for index, short in enumerate(result["shorts"])
        ]
        job["clip_paths"] = [short.get("clip_url") for short in result["shorts"]]
        job["status"] = "completed"
    except Exception as exc:
        job["error"] = _safe_error(exc, settings["api_key"])
        job["status"] = "failed"
    finally:
        with _lock:
            _active_job = None


@app.get("/")
def index():
    return render_template("index.html", csrf_token=CSRF_TOKEN)


@app.post("/api/jobs")
def create_job():
    global _active_job
    if request.form.get("csrf_token") != CSRF_TOKEN:
        return jsonify(error="Недействительный запрос. Обновите страницу."), 403
    upload = request.files.get("video")
    has_upload = bool(upload and upload.filename)
    raw_url = request.form.get("source_url", "").strip()
    if has_upload == bool(raw_url):
        return jsonify(error="Выберите MP4 или вставьте ссылку YouTube — что-то одно"), 400
    if has_upload:
        if not upload.filename.lower().endswith(".mp4"):
            return jsonify(error="Нужен файл MP4"), 400
        header = upload.stream.read(12)
        upload.stream.seek(0)
        if len(header) < 12 or header[4:8] != b"ftyp":
            return jsonify(error="Файл не похож на MP4"), 400
    else:
        try:
            raw_url = _youtube_url(raw_url)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
    try:
        settings = _settings(request.form)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    with _lock:
        if _active_job is not None:
            return jsonify(error="Дождитесь завершения текущей обработки"), 409
        job_id = uuid4().hex
        _active_job = job_id
        _jobs[job_id] = {"id": job_id, "status": "queued", "shorts": [], "provider": settings["provider"], "model": settings["model"]}
    folder = JOBS_DIR / job_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
        if has_upload:
            upload.save(folder / "source.mp4")
            _jobs[job_id]["source"] = str(folder / "source.mp4")
        else:
            _jobs[job_id]["source"] = raw_url
    except Exception:
        with _lock:
            _active_job = None
            _jobs.pop(job_id, None)
        return jsonify(error="Не удалось сохранить MP4. Проверьте место на диске."), 500
    Thread(target=_run_job, args=(job_id, settings), daemon=True).start()
    return jsonify(id=job_id, status="queued"), 202


@app.get("/api/jobs/<job_id>")
def get_job(job_id):
    job = _jobs.get(job_id)
    if job is None:
        abort(404)
    return jsonify({key: value for key, value in job.items() if key != "clip_paths"})


@app.get("/api/jobs/<job_id>/clips/<int:index>")
def get_clip(job_id, index):
    job = _jobs.get(job_id)
    paths = job.get("clip_paths", []) if job else []
    if index < 0 or index >= len(paths) or not paths[index]:
        abort(404)
    path = Path(paths[index]).resolve()
    if not path.is_relative_to((JOBS_DIR / job_id).resolve()) or not path.is_file():
        abort(404)
    return send_file(path, mimetype="video/mp4")


if __name__ == "__main__":
    print("Откройте http://127.0.0.1:8765 в браузере")
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)
