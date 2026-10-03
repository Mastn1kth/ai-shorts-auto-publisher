"""Coordinate independent platform publishing without losing partial results."""

import os
import tempfile
from typing import Dict, Iterable, List, Optional

import requests

from .base import build_metadata
from .ledger import PublishingLedger
from .vk import VKPublisher
from .youtube import YouTubePublisher

MAX_REMOTE_CLIP_BYTES = 1_000_000_000


def validate_publish_request(platforms: Iterable[str], privacy_status: str) -> List[str]:
    platforms = list(dict.fromkeys(p.strip().lower() for p in platforms if p.strip()))
    invalid = sorted(set(platforms) - {"youtube", "vk"})
    if invalid:
        raise ValueError(f"Unsupported publishing platforms: {', '.join(invalid)}")
    if privacy_status not in {"private", "unlisted", "public"}:
        raise ValueError("publish_privacy must be private, unlisted, or public")
    if "vk" in platforms and privacy_status == "unlisted":
        raise ValueError("VK Video does not support unlisted visibility")
    return platforms


def _publisher(platform: str):
    return {"youtube": YouTubePublisher, "vk": VKPublisher}[platform]()


def publish_shorts(
    shorts: List[Dict], platforms: Iterable[str], privacy_status: str = "private",
    dry_run: bool = False, source_id: Optional[str] = None, force_republish: bool = False,
) -> List[Dict]:
    """Publish each successfully rendered short to requested platforms."""
    platforms = validate_publish_request(platforms, privacy_status)
    ledger = None if dry_run else PublishingLedger()
    results = []
    for short in shorts:
        video_path = short.get("clip_url")
        item = {**short, "publishing": {}}
        if not video_path:
            reason = short.get("error") or "clip has no video path or URL"
            item["publishing"] = {
                platform: {"platform": platform, "status": "failed", "error": reason}
                for platform in platforms
            }
            results.append(item)
            continue
        for platform in platforms:
            temporary_path = None
            try:
                key = None if dry_run else ledger.key(platform, video_path, short, source_id)
                previous = None if dry_run or force_republish else ledger.find(key)
                if previous:
                    item["publishing"][platform] = {**previous, "status": "already_uploaded", "previous_status": previous["status"]}
                    continue
                publish_path = video_path
                # API mode returns hosted clip URLs; upload-based publishers need a local file.
                if not dry_run and platform in {"youtube", "vk"} and str(video_path).startswith(("http://", "https://")):
                    if not video_path.startswith("https://"):
                        raise ValueError("Hosted clip URL must use HTTPS")
                    download = requests.get(video_path, stream=True, timeout=(30, 300))
                    try:
                        download.raise_for_status()
                        fd, temporary_path = tempfile.mkstemp(prefix="short-publish-", suffix=".mp4")
                        downloaded = 0
                        with os.fdopen(fd, "wb") as output:
                            for chunk in download.iter_content(chunk_size=1024 * 1024):
                                downloaded += len(chunk)
                                if downloaded > MAX_REMOTE_CLIP_BYTES:
                                    raise ValueError("Hosted clip is larger than the 1 GB download limit")
                                output.write(chunk)
                        if downloaded == 0:
                            raise ValueError("Hosted clip is empty")
                        publish_path = temporary_path
                    finally:
                        download.close()
                outcome = _publisher(platform).publish(
                    publish_path,
                    build_metadata(short, platform),
                    privacy_status=privacy_status,
                    dry_run=dry_run,
                )
                item["publishing"][platform] = outcome
                if ledger and outcome.get("status") == "uploaded":
                    try:
                        ledger.record(key, outcome)
                    except Exception as exc:
                        item["publishing"][platform]["tracking_error"] = (
                            f"Upload succeeded, but publishing ledger could not be saved: {exc}"
                        )
            except Exception as exc:
                item["publishing"][platform] = {"platform": platform, "status": "failed", "error": str(exc)}
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
        results.append(item)
    return results
