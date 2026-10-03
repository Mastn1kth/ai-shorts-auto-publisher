"""Coordinate independent platform publishing without losing partial results."""

import os
import tempfile
from typing import Dict, Iterable, List

import requests

from .base import build_metadata
from .instagram import InstagramPublisher
from .vk import VKPublisher
from .youtube import YouTubePublisher


def _publisher(platform: str):
    return {"youtube": YouTubePublisher, "vk": VKPublisher, "instagram": InstagramPublisher}[platform]()


def publish_shorts(shorts: List[Dict], platforms: Iterable[str], privacy_status: str = "private", dry_run: bool = False) -> List[Dict]:
    """Publish each successfully rendered short to requested platforms."""
    platforms = [p.strip().lower() for p in platforms if p.strip()]
    invalid = sorted(set(platforms) - {"youtube", "vk", "instagram"})
    if invalid:
        raise ValueError(f"Unsupported publishing platforms: {', '.join(invalid)}")
    results = []
    for short in shorts:
        video_path = short.get("clip_url")
        item = {**short, "publishing": {}}
        if not video_path:
            item["publishing_error"] = "clip has no local video path"
            results.append(item)
            continue
        for platform in platforms:
            temporary_path = None
            try:
                publish_path = video_path
                # API mode returns hosted clip URLs; upload-based publishers need a local file.
                if (not dry_run and platform in {"youtube", "vk"}
                        and str(video_path).startswith(("http://", "https://"))):
                    download = requests.get(video_path, timeout=1800)
                    download.raise_for_status()
                    suffix = ".mp4"
                    fd, temporary_path = tempfile.mkstemp(prefix="short-publish-", suffix=suffix)
                    with os.fdopen(fd, "wb") as output:
                        output.write(download.content)
                    publish_path = temporary_path
                item["publishing"][platform] = _publisher(platform).publish(
                    publish_path,
                    build_metadata(short, platform),
                    privacy_status=privacy_status,
                    dry_run=dry_run,
                )
            except Exception as exc:
                item["publishing"][platform] = {"platform": platform, "status": "failed", "error": str(exc)}
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
        results.append(item)
    return results
