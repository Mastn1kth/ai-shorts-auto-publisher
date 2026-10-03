"""TikTok Content Posting API publisher (Direct Post)."""

import os
from pathlib import Path

import requests
from .credentials import get_secret

class TikTokPublisher:
    name = "tiktok"

    def __init__(self, access_token=None):
        self.access_token = access_token or get_secret("TIKTOK_ACCESS_TOKEN") or os.getenv("TIKTOK_ACCESS_TOKEN")

    def publish(self, video_path, metadata, privacy_status="private", dry_run=False):
        if dry_run:
            return {"platform": self.name, "status": "dry_run"}
        if not self.access_token:
            raise ValueError("Для TikTok сохраните Access Token Content Posting API")
        path = Path(video_path)
        if not path.is_file():
            raise ValueError("TikTok принимает только локальный MP4-файл")
        size = path.stat().st_size
        privacy = {"private": "SELF_ONLY", "public": "PUBLIC_TO_EVERYONE"}.get(privacy_status, "SELF_ONLY")
        payload = {"post_info": {"title": (metadata.get("description") or metadata.get("title") or "")[:2200], "privacy_level": privacy, "disable_comment": False, "disable_duet": False, "disable_stitch": False, "is_aigc": True}, "source_info": {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": size, "total_chunk_count": 1}}
        headers = {"Authorization": f"Bearer {self.access_token}", "Content-Type": "application/json; charset=UTF-8"}
        response = requests.post("https://open.tiktokapis.com/v2/post/publish/video/init/", json=payload, headers=headers, timeout=60)
        response.raise_for_status()
        body = response.json()
        error = body.get("error", {})
        if error.get("code") not in (None, "ok"):
            raise ValueError(error.get("message") or error.get("code"))
        data = body.get("data") or {}
        upload_url, publish_id = data.get("upload_url"), data.get("publish_id")
        if not upload_url or not publish_id:
            raise ValueError("TikTok не вернул адрес загрузки")
        with path.open("rb") as stream:
            upload = requests.put(upload_url, data=stream, headers={"Content-Type": "video/mp4", "Content-Range": f"bytes 0-{size - 1}/{size}"}, timeout=(60, 600))
        upload.raise_for_status()
        return {"platform": self.name, "status": "uploaded", "external_id": publish_id, "note": "TikTok обрабатывает публикацию асинхронно"}
