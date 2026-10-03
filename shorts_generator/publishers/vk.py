"""VK Video publisher using video.save followed by upload_url upload."""

import os
from typing import Dict, Optional

import requests

from .base import PublisherError
from .credentials import get_secret


class VKPublisher:
    name = "vk"

    def __init__(self, access_token: Optional[str] = None, group_id: Optional[str] = None):
        self.access_token = access_token or get_secret("VK_ACCESS_TOKEN")
        # The desktop app targets the owner's personal VK Video profile.
        # Keep the argument for CLI/API compatibility, but never inherit a
        # previously saved community ID into a profile upload.
        self.group_id = None
        self.api_version = os.getenv("VK_API_VERSION", "5.199")
        self.api_url = "https://api.vk.com/method/video.save"

    def publish(self, video_path: str, metadata: Dict, privacy_status: str = "private", dry_run: bool = False) -> Dict:
        if dry_run:
            return {"platform": self.name, "status": "dry_run", "video_path": video_path}
        if privacy_status not in {"private", "public"}:
            raise PublisherError("VK Video visibility must be private or public")
        if not self.access_token:
            raise PublisherError("VK_ACCESS_TOKEN is not configured")
        if not os.path.isfile(video_path):
            raise PublisherError(f"Video file not found: {video_path}")
        params = {
            "access_token": self.access_token,
            "v": self.api_version,
            "name": metadata["title"],
            "description": metadata.get("description", ""),
            "is_private": 1 if privacy_status == "private" else 0,
            "wallpost": 0,
        }
        if self.group_id:
            params["group_id"] = self.group_id
        try:
            response = requests.post(self.api_url, data=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            if "error" in payload:
                raise PublisherError(payload["error"].get("error_msg", "VK video.save failed"))
            saved = payload.get("response") or {}
            upload_url = saved.get("upload_url")
            if not upload_url:
                raise PublisherError("VK did not return upload_url")
            with open(video_path, "rb") as video_file:
                upload = requests.post(upload_url, files={"video_file": video_file}, timeout=1800)
            upload.raise_for_status()
            upload_payload = upload.json() if upload.content else {}
            if "error" in upload_payload:
                error = upload_payload["error"]
                raise PublisherError(error.get("error_msg", str(error)) if isinstance(error, dict) else str(error))
            owner_id = saved.get("owner_id")
            video_id = saved.get("video_id")
            result = {
                "platform": self.name,
                "status": "uploaded",
                "external_id": str(video_id) if video_id is not None else None,
                "response": upload_payload,
            }
            if owner_id is not None and video_id is not None:
                result["url"] = f"https://vk.com/video{owner_id}_{video_id}"
            return result
        except PublisherError:
            raise
        except requests.RequestException as exc:
            raise PublisherError(f"VK upload failed: {exc}") from exc
