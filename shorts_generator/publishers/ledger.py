"""Durable record of accepted uploads for sequential CLI runs."""

import hashlib
import json
import os
import tempfile
from typing import Dict, Optional


def _account_marker(platform: str) -> str:
    if platform == "youtube":
        account_id = os.getenv("YOUTUBE_ACCOUNT_ID", "").strip()
        if account_id:
            return "account:" + account_id
        return "token-file:" + os.path.abspath(os.getenv("YOUTUBE_TOKEN_FILE", "youtube-token.json"))
    if platform == "vk":
        group = os.getenv("VK_GROUP_ID", "").strip()
        if group:
            return f"group:{group}"
        token = os.getenv("VK_ACCESS_TOKEN", "").strip()
        return "user-token:" + hashlib.sha256(token.encode("utf-8")).hexdigest()
    raise ValueError(f"Unsupported platform: {platform}")


def _clip_marker(video_path: str, source_id: Optional[str], short: Dict) -> str:
    if os.path.isfile(video_path):
        digest = hashlib.sha256()
        with open(video_path, "rb") as video:
            for chunk in iter(lambda: video.read(1024 * 1024), b""):
                digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    if video_path.startswith("https://"):
        if source_id is not None and "start_time" in short and "end_time" in short:
            return f"source:{source_id}|{float(short['start_time']):.3f}|{float(short['end_time']):.3f}"
        return "url:" + video_path
    raise FileNotFoundError(f"Clip file not found: {video_path}")


class PublishingLedger:
    def __init__(self, path: Optional[str] = None):
        configured = path or os.getenv("PUBLISH_LEDGER_FILE", "")
        self.path = configured or os.path.join("output", "publishing-ledger.json")
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as saved:
                contents = json.load(saved)
            if not isinstance(contents, dict) or contents.get("version") != 1 or not isinstance(contents.get("items"), dict):
                raise ValueError(f"Invalid publishing ledger: {self.path}")
            self.items = contents["items"]
        else:
            self.items = {}

    def key(self, platform: str, video_path: str, short: Dict, source_id: Optional[str]) -> str:
        identity = [platform, _account_marker(platform), _clip_marker(video_path, source_id, short)]
        payload = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def find(self, key: str) -> Optional[Dict]:
        result = self.items.get(key)
        if result and result.get("status") != "uploaded":
            raise ValueError(f"Invalid publishing ledger entry in {self.path}")
        return result

    def record(self, key: str, result: Dict) -> None:
        parent = os.path.dirname(os.path.abspath(self.path))
        os.makedirs(parent, exist_ok=True)
        updated = {**self.items, key: result}
        fd, temporary_path = tempfile.mkstemp(prefix=".publishing-ledger-", suffix=".tmp", dir=parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"version": 1, "items": updated}, output, ensure_ascii=False, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_path, self.path)
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        self.items = updated
