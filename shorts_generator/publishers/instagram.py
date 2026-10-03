"""Instagram Reels publisher using the official container workflow."""

import os
import time
from typing import Callable, Dict, Optional

import requests

from .base import PublisherError


class InstagramPublisher:
    name = "instagram"

    def __init__(self, access_token: Optional[str] = None, user_id: Optional[str] = None,
                 public_url_factory: Optional[Callable[[str], str]] = None):
        self.access_token = access_token or os.getenv("INSTAGRAM_ACCESS_TOKEN", "").strip()
        self.user_id = user_id or os.getenv("INSTAGRAM_USER_ID", "").strip()
        self.api_version = os.getenv("INSTAGRAM_API_VERSION", "v24.0")
        self.public_url_factory = public_url_factory
        self.base_url = f"https://graph.facebook.com/{self.api_version}"
        self.poll_interval = float(os.getenv("INSTAGRAM_POLL_INTERVAL", "5"))
        self.poll_timeout = float(os.getenv("INSTAGRAM_POLL_TIMEOUT", "900"))

    def _public_url(self, video_path: str) -> str:
        if video_path.startswith(("http://", "https://")):
            return video_path
        if self.public_url_factory:
            return self.public_url_factory(video_path)
        template = os.getenv("INSTAGRAM_VIDEO_URL_TEMPLATE", "").strip()
        if template:
            return template.format(filename=os.path.basename(video_path), path=video_path)
        raise PublisherError(
            "Instagram requires a publicly reachable HTTPS video URL. "
            "Configure INSTAGRAM_VIDEO_URL_TEMPLATE or an object-storage adapter."
        )

    def publish(self, video_path: str, metadata: Dict, privacy_status: str = "private", dry_run: bool = False) -> Dict:
        if dry_run:
            return {"platform": self.name, "status": "dry_run", "video_path": video_path}
        if not self.access_token or not self.user_id:
            raise PublisherError("INSTAGRAM_ACCESS_TOKEN and INSTAGRAM_USER_ID are required")
        if not os.path.isfile(video_path):
            raise PublisherError(f"Video file not found: {video_path}")
        if privacy_status in {"private", "draft"}:
            raise PublisherError("Instagram Graph API does not provide a private Reel mode; use dry-run instead")
        video_url = self._public_url(video_path)
        try:
            container_response = requests.post(
                f"{self.base_url}/{self.user_id}/media",
                params={
                    "media_type": "REELS",
                    "video_url": video_url,
                    "caption": metadata.get("caption", ""),
                    "share_to_feed": os.getenv("INSTAGRAM_SHARE_TO_FEED", "true").lower() == "true",
                    "access_token": self.access_token,
                },
                timeout=30,
            )
            container_response.raise_for_status()
            container = container_response.json()
            if "error" in container:
                raise PublisherError(container["error"].get("message", "Instagram container creation failed"))
            creation_id = container.get("id")
            if not creation_id:
                raise PublisherError("Instagram did not return a creation id")

            deadline = time.monotonic() + self.poll_timeout
            while True:
                status_response = requests.get(
                    f"{self.base_url}/{creation_id}",
                    params={"fields": "status_code,status", "access_token": self.access_token},
                    timeout=30,
                )
                status_response.raise_for_status()
                status = status_response.json()
                status_code = status.get("status_code")
                if status_code == "FINISHED":
                    break
                if status_code in {"ERROR", "EXPIRED"}:
                    raise PublisherError(status.get("status") or f"Instagram container status: {status_code}")
                if time.monotonic() >= deadline:
                    raise PublisherError("Timed out waiting for Instagram media container")
                time.sleep(self.poll_interval)

            published = requests.post(
                f"{self.base_url}/{self.user_id}/media_publish",
                params={"creation_id": creation_id, "access_token": self.access_token},
                timeout=30,
            )
            published.raise_for_status()
            payload = published.json()
            if "error" in payload:
                raise PublisherError(payload["error"].get("message", "Instagram publish failed"))
            return {"platform": self.name, "status": "published", "external_id": payload.get("id"), "creation_id": creation_id}
        except PublisherError:
            raise
        except requests.RequestException as exc:
            raise PublisherError(f"Instagram upload failed: {exc}") from exc
