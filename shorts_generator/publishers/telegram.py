"""Publish MP4 clips to a Telegram channel through the official Bot API."""

import os
from contextlib import ExitStack
from typing import Dict, Optional

import requests

from .base import PublisherError
from .credentials import get_secret


MAX_VIDEO_BYTES = 50 * 1024 * 1024


class TelegramPublisher:
    name = "telegram"

    def __init__(self, bot_token: Optional[str] = None, chat_id: Optional[str] = None):
        self.bot_token = bot_token or get_secret("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or get_secret("TELEGRAM_CHAT_ID")

    def publish(self, video_path: str, metadata: Dict, privacy_status: str = "public", dry_run: bool = False) -> Dict:
        if dry_run:
            return {"platform": self.name, "status": "dry_run", "video_path": video_path}
        if privacy_status != "public":
            raise PublisherError("Telegram channel visibility is configured in Telegram; use --publish-privacy public")
        if not self.bot_token or not self.chat_id:
            raise PublisherError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be configured")
        if not os.path.isfile(video_path):
            raise PublisherError(f"Video file not found: {video_path}")
        if os.path.getsize(video_path) > MAX_VIDEO_BYTES:
            raise PublisherError("Telegram Bot API sendVideo limit is 50 MB; compress the clip before publishing")

        endpoint = f"https://api.telegram.org/bot{self.bot_token}/sendVideo"
        try:
            with ExitStack() as stack:
                video = stack.enter_context(open(video_path, "rb"))
                files = {"video": (os.path.basename(video_path), video, "video/mp4")}
                thumbnail_path = metadata.get("thumbnail_path")
                if thumbnail_path and os.path.isfile(thumbnail_path) and os.path.getsize(thumbnail_path) < 200_000:
                    thumbnail = stack.enter_context(open(thumbnail_path, "rb"))
                    files["thumbnail"] = ("thumbnail.jpg", thumbnail, "image/jpeg")
                response = requests.post(
                    endpoint,
                    data={"chat_id": self.chat_id, "caption": metadata["caption"], "supports_streaming": "true"},
                    files=files,
                    timeout=(30, 1800),
                )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            # requests exceptions can include the URL, which embeds the bot token.
            raise PublisherError("Telegram upload request failed; check network, bot rights and video size") from None
        if not payload.get("ok"):
            raise PublisherError("Telegram rejected the upload; check bot rights and channel ID")
        message_id = (payload.get("result") or {}).get("message_id")
        if not isinstance(message_id, int):
            raise PublisherError("Telegram response did not include a message ID")
        result = {"platform": self.name, "status": "uploaded", "external_id": str(message_id)}
        if self.chat_id.startswith("@"):
            result["url"] = f"https://t.me/{self.chat_id[1:]}/{message_id}"
        return result
