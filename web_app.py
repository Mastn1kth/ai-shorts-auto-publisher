"""Local-only web interface for MP4-to-shorts jobs."""

import os
import re
import secrets
import json
import subprocess
import time
import sys
from datetime import datetime, timedelta
from pathlib import Path
from threading import Lock, Thread
from urllib.parse import urlparse
from uuid import uuid4

from flask import Flask, abort, jsonify, render_template, request, send_file

from shorts_generator import generate_shorts
from shorts_generator.local.llm import make_llm
from shorts_generator.local.downloader import _extract_youtube_video_id
from shorts_generator.publishers.service import validate_publish_request
from shorts_generator.publishers.service import publish_shorts
from shorts_generator.publishers.credentials import get_secret, save_secret
from shorts_generator.publishers.youtube import YouTubePublisher


ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if getattr(sys, "frozen", False):
    DATA_ROOT = Path(os.getenv("LOCALAPPDATA", Path.home())) / "ShortformStudio"
else:
    DATA_ROOT = ROOT / "output"
JOBS_DIR = DATA_ROOT / "ui-jobs"
UI_CREDENTIALS_DIR = DATA_ROOT / "credentials"
YOUTUBE_CLIENT_FILE = UI_CREDENTIALS_DIR / "client_secret.json"
YOUTUBE_TOKEN_FILE = UI_CREDENTIALS_DIR / "youtube-token.json"
if YOUTUBE_CLIENT_FILE.is_file():
    os.environ["YOUTUBE_CLIENT_SECRET_FILE"] = str(YOUTUBE_CLIENT_FILE)
    os.environ["YOUTUBE_TOKEN_FILE"] = str(YOUTUBE_TOKEN_FILE)
os.environ.setdefault("PUBLISH_LEDGER_FILE", str(DATA_ROOT / "publishing-ledger.json"))
CSRF_TOKEN = secrets.token_urlsafe(32)
MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024
AI_SERVICES = (
    ("openai", "OPENAI_API_KEY", "OPENAI_MODEL", "gpt-4o-mini"),
    ("gemini", "GEMINI_API_KEY", "GEMINI_MODEL", "gemini-2.5-flash"),
    ("openrouter", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openai/gpt-4o-mini"),
    ("groq", "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-20b"),
)

app = Flask(__name__, template_folder=str(ROOT / "web" / "templates"), static_folder=str(ROOT / "web" / "static"))
app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
_jobs = {}
_lock = Lock()
_active_job = None
_publish_lock = Lock()
_oauth_state = {"status": "idle", "error": None}


def _save_job(job: dict) -> None:
    folder = JOBS_DIR / job["id"]
    target = folder / "job.json"
    temporary = folder / "job.json.tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        json.dump(job, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, target)


def _schedule_times(count: int, interval_minutes: int, start_at: str) -> list:
    now = datetime.now().astimezone()
    if start_at:
        start = datetime.fromisoformat(start_at).astimezone()
        if start < now - timedelta(seconds=2):
            raise ValueError("Время первой публикации должно быть в будущем")
        start = max(start, now)
    else:
        start = now
    return [(start + timedelta(minutes=index * interval_minutes)).isoformat() for index in range(count)]


def _queue_start(interval_minutes: int, start_at: str) -> str:
    """Keep clips from separate jobs one interval apart as well."""
    requested = datetime.fromisoformat(_schedule_times(1, interval_minutes, start_at)[0])
    for other in _jobs.values():
        if other.get("publish_state") != "pending" or other.get("dry_run"):
            continue
        for short in other.get("shorts", []):
            scheduled = short.get("scheduled_at")
            if scheduled:
                due = datetime.fromisoformat(scheduled)
                if due >= requested:
                    requested = due + timedelta(minutes=interval_minutes)
    return requested.isoformat()


def _thumbnail(video_path: str, target: Path) -> bool:
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.5", "-i", video_path,
             "-frames:v", "1", "-vf", "scale=320:320:force_original_aspect_ratio=decrease", "-q:v", "4", str(target)],
            check=True, capture_output=True, timeout=60,
        )
        return target.is_file()
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _safe_error(error: Exception, submitted_key: str) -> str:
    message = str(error)
    keys = [submitted_key] + [get_secret(name) for name in (
        "OPENAI_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "GROQ_API_KEY",
        "VK_ACCESS_TOKEN", "TELEGRAM_BOT_TOKEN",
    )]
    for key in keys:
        if key:
            message = message.replace(key, "[hidden]")
    return message[:500] or type(error).__name__


def _settings(form):
    selected = next(((provider, key, os.getenv(model_var, default).strip() or default)
                     for provider, key_name, model_var, default in AI_SERVICES
                     if (key := get_secret(key_name))), None)
    if selected is None:
        raise ValueError("Добавьте API-ключ ИИ в настройках")
    provider, api_key, model = selected
    try:
        num_clips = int(form.get("num_clips", "3"))
    except ValueError as exc:
        raise ValueError("Количество клипов должно быть числом") from exc
    if not 1 <= num_clips <= 10:
        raise ValueError("Можно создать от 1 до 10 клипов за запуск")
    privacy = form.get("privacy", "private")
    platforms = validate_publish_request(form.getlist("platforms"), privacy)
    try:
        interval_minutes = int(form.get("interval_minutes", "60"))
    except ValueError as exc:
        raise ValueError("Интервал публикации должен быть числом") from exc
    if not 1 <= interval_minutes <= 10080:
        raise ValueError("Интервал должен быть от 1 минуты до 7 дней")
    start_at = form.get("start_at", "").strip()
    if start_at:
        try:
            _schedule_times(1, interval_minutes, start_at)
        except (ValueError, OverflowError) as exc:
            raise ValueError("Некорректное время первой публикации") from exc
    return {
        "provider": provider,
        "model": model,
        "api_key": api_key,
        "base_url": "",
        "num_clips": num_clips,
        "platforms": platforms,
        "privacy": privacy,
        "dry_run": form.get("dry_run") == "on",
        "interval_minutes": interval_minutes,
        "start_at": start_at,
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
        _save_job(job)
        llm = make_llm(settings["provider"], settings["model"], settings["api_key"], settings["base_url"])
        result = generate_shorts(
            job["source"],
            mode="local",
            num_clips=settings["num_clips"],
            llm_fn=llm,
            output_dir=str(JOBS_DIR / job_id),
        )
        for index, short in enumerate(result["shorts"]):
            if short.get("clip_url"):
                thumbnail_path = JOBS_DIR / job_id / f"thumbnail_{index:02d}.jpg"
                if _thumbnail(short["clip_url"], thumbnail_path):
                    short["thumbnail_path"] = str(thumbnail_path)
        job["raw_shorts"] = result["shorts"]
        job["clip_paths"] = [short.get("clip_url") for short in result["shorts"]]
        due_times = _schedule_times(
            len(result["shorts"]), settings["interval_minutes"],
            "" if settings["dry_run"] else _queue_start(settings["interval_minutes"], settings["start_at"]),
        ) if settings["platforms"] else []
        job["shorts"] = [
            {
                "title": short.get("title"),
                "description": "\n\n".join(part for part in (short.get("hook_sentence"), short.get("virality_reason")) if part),
                "score": short.get("score"),
                "start_time": short.get("start_time"),
                "end_time": short.get("end_time"),
                "error": short.get("error"),
                "publishing": {platform: {"status": "scheduled"} for platform in settings["platforms"]} if short.get("clip_url") else {},
                "video_url": f"/api/jobs/{job_id}/clips/{index}" if short.get("clip_url") else None,
                "thumbnail_url": f"/api/jobs/{job_id}/thumbnails/{index}" if short.get("thumbnail_path") else None,
                "scheduled_at": due_times[index] if due_times and short.get("clip_url") else None,
            }
            for index, short in enumerate(result["shorts"])
        ]
        job["platforms"] = settings["platforms"]
        job["privacy"] = settings["privacy"]
        job["dry_run"] = settings["dry_run"]
        job["publish_state"] = "pending" if settings["platforms"] else "none"
        job["status"] = "completed"
        _save_job(job)
        if settings["platforms"]:
            Thread(target=_publish_job, args=(job_id,), daemon=True).start()
    except Exception as exc:
        job["error"] = _safe_error(exc, settings["api_key"])
        job["status"] = "failed"
        _save_job(job)
    finally:
        with _lock:
            _active_job = None


def _publish_job(job_id: str) -> None:
    job = _jobs[job_id]
    for index, short in enumerate(job["raw_shorts"]):
        if not short.get("clip_url"):
            continue
        if all(status.get("status") in {"uploaded", "already_uploaded", "dry_run"}
               for status in job["shorts"][index]["publishing"].values()):
            continue
        due = datetime.fromisoformat(job["shorts"][index]["scheduled_at"])
        while True:
            seconds = (due - datetime.now().astimezone()).total_seconds()
            if seconds <= 0:
                break
            time.sleep(min(seconds, 60))
        try:
            with _publish_lock:
                result = publish_shorts(
                    [short], job["platforms"], privacy_status=job["privacy"],
                    dry_run=job["dry_run"], source_id=job["source"],
                )[0]
            job["shorts"][index]["publishing"] = result["publishing"]
        except Exception as exc:
            job["shorts"][index]["publishing"] = {
                platform: {"status": "failed", "error": _safe_error(exc, "")}
                for platform in job["platforms"]
            }
        _save_job(job)
    job["publish_state"] = "finished"
    _save_job(job)


def restore_jobs() -> None:
    """Resume unfinished publication queues after a normal server restart."""
    if not JOBS_DIR.exists():
        return
    for state_file in sorted(JOBS_DIR.glob("*/job.json"), key=lambda path: path.stat().st_mtime):
        try:
            with open(state_file, encoding="utf-8") as stream:
                job = json.load(stream)
            if job.get("id") != state_file.parent.name:
                continue
            _jobs[job["id"]] = job
            if job.get("status") == "completed" and job.get("publish_state") == "pending":
                Thread(target=_publish_job, args=(job["id"],), daemon=True).start()
            elif job.get("status") in {"queued", "running"}:
                job["status"] = "failed"
                job["error"] = "Обработка прервана закрытием программы. Добавьте исходное видео заново."
                _save_job(job)
        except (OSError, ValueError, KeyError, TypeError):
            continue


def _connection_status() -> dict:
    return {
        "ai_saved": {provider: bool(get_secret(key_name)) for provider, key_name, _, _ in AI_SERVICES},
        "youtube_client_ready": Path(os.getenv("YOUTUBE_CLIENT_SECRET_FILE", "client_secret.json")).is_file(),
        "youtube_token_ready": Path(os.getenv("YOUTUBE_TOKEN_FILE", "youtube-token.json")).is_file(),
        "youtube_auth": dict(_oauth_state),
        "vk_token_saved": bool(get_secret("VK_ACCESS_TOKEN")),
        "vk_group_id": get_secret("VK_GROUP_ID"),
        "telegram_token_saved": bool(get_secret("TELEGRAM_BOT_TOKEN")),
        "telegram_chat_id": get_secret("TELEGRAM_CHAT_ID"),
    }


def _authorize_youtube() -> None:
    try:
        publisher = YouTubePublisher()
        publisher._service()
        _oauth_state.update(status="connected", error=None)
    except Exception as exc:
        _oauth_state.update(status="failed", error=_safe_error(exc, ""))


@app.get("/api/connections")
def get_connections():
    return jsonify(_connection_status())


@app.post("/api/connections/tokens")
def save_connections():
    if request.form.get("csrf_token") != CSRF_TOKEN:
        return jsonify(error="Недействительный запрос. Обновите страницу."), 403
    allowed = {"VK_ACCESS_TOKEN", "VK_GROUP_ID", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"} | {
        key_name for _, key_name, _, _ in AI_SERVICES
    }
    for name in allowed:
        value = request.form.get(name, "").strip()
        if len(value) > 4096 or "\n" in value or "\r" in value:
            return jsonify(error=f"Некорректное значение {name}"), 400
    try:
        for name in allowed:
            value = request.form.get(name, "").strip()
            if value:
                save_secret(name, value)
    except Exception:
        return jsonify(error="Не удалось сохранить ключ в системном хранилище. Проверьте Windows Credential Manager."), 500
    return jsonify(_connection_status())


@app.post("/api/connections/youtube/client")
def save_youtube_client():
    if request.form.get("csrf_token") != CSRF_TOKEN:
        return jsonify(error="Недействительный запрос. Обновите страницу."), 403
    upload = request.files.get("client_file")
    if not upload or not upload.filename or not upload.filename.lower().endswith(".json"):
        return jsonify(error="Выберите JSON-файл OAuth-клиента Google"), 400
    contents = upload.read(1024 * 1024 + 1)
    if len(contents) > 1024 * 1024:
        return jsonify(error="Файл OAuth слишком большой"), 400
    try:
        payload = json.loads(contents)
        installed = payload["installed"]
        if not installed.get("client_id") or not installed.get("client_secret"):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        return jsonify(error="Нужен OAuth JSON типа Desktop, созданный в Google Cloud"), 400
    UI_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    YOUTUBE_CLIENT_FILE.write_bytes(contents)
    os.environ["YOUTUBE_CLIENT_SECRET_FILE"] = str(YOUTUBE_CLIENT_FILE)
    os.environ["YOUTUBE_TOKEN_FILE"] = str(YOUTUBE_TOKEN_FILE)
    return jsonify(_connection_status())


@app.post("/api/connections/youtube/authorize")
def authorize_youtube():
    if request.form.get("csrf_token") != CSRF_TOKEN:
        return jsonify(error="Недействительный запрос. Обновите страницу."), 403
    if not _connection_status()["youtube_client_ready"]:
        return jsonify(error="Сначала добавьте OAuth JSON типа Desktop"), 400
    if _oauth_state["status"] == "pending":
        return jsonify(error="Авторизация уже запущена"), 409
    _oauth_state.update(status="pending", error=None)
    Thread(target=_authorize_youtube, daemon=True).start()
    return jsonify(status="pending"), 202


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
        _jobs[job_id] = {"id": job_id, "status": "queued", "shorts": [], "provider": settings["provider"], "model": settings["model"], "created_at": datetime.now().astimezone().isoformat()}
    folder = JOBS_DIR / job_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
        if has_upload:
            upload.save(folder / "source.mp4")
            _jobs[job_id]["source"] = str(folder / "source.mp4")
        else:
            _jobs[job_id]["source"] = raw_url
        _save_job(_jobs[job_id])
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
    return jsonify({key: value for key, value in job.items() if key not in {"clip_paths", "raw_shorts", "source"}})


@app.get("/api/jobs/latest")
def get_latest_job():
    if not _jobs:
        return jsonify(id=None)
    return jsonify(id=next(reversed(_jobs)))


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


@app.get("/api/jobs/<job_id>/thumbnails/<int:index>")
def get_thumbnail(job_id, index):
    if job_id not in _jobs or index < 0 or index >= len(_jobs[job_id].get("shorts", [])):
        abort(404)
    path = JOBS_DIR / job_id / f"thumbnail_{index:02d}.jpg"
    if not path.is_file():
        abort(404)
    return send_file(path, mimetype="image/jpeg")


if __name__ == "__main__":
    restore_jobs()
    print("Откройте http://127.0.0.1:8765 в браузере")
    app.run(host="127.0.0.1", port=8765, debug=False, use_reloader=False)
