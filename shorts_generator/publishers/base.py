"""Shared publisher contracts and metadata helpers."""

from typing import Dict


class PublisherError(RuntimeError):
    """A recoverable or platform-specific publishing failure."""


def build_metadata(short: Dict, platform: str) -> Dict:
    """Build platform-neutral metadata from a generated short."""
    title = str(short.get("title") or "AI generated short").strip()
    hook = str(short.get("hook_sentence") or "").strip()
    reason = str(short.get("virality_reason") or "").strip()
    description = "\n\n".join(part for part in (hook, reason) if part)
    if platform == "youtube":
        description = (description + "\n\n#shorts").strip()
        return {"title": title[:100], "description": description[:5000], "tags": ["shorts"]}
    if platform == "vk":
        return {"title": title[:250], "description": description[:2048]}
    if platform == "telegram":
        return {"caption": "\n\n".join(part for part in (title, description) if part)[:1024]}
    raise ValueError(f"Unsupported platform: {platform}")
