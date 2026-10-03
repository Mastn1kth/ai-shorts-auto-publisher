"""Sequential movie/episode slicing without AI highlight selection."""

from __future__ import annotations

import math
import subprocess
from pathlib import Path

from .clipper import crop_highlights_local
from .downloader import download_youtube_local
from .transcriber import transcribe_local


def media_duration(source: str) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", source],
        check=True, capture_output=True, text=True, timeout=60,
    )
    return max(0.0, float(result.stdout.strip()))


def build_sequential_parts(source: str, part_duration: int, aspect_ratio: str = "9:16", out_dir: str | None = None) -> dict:
    """Download/inspect a source and create every consecutive part."""
    source_path = download_youtube_local(source, out_dir=out_dir)
    duration = media_duration(source_path)
    if duration <= 0:
        raise RuntimeError("Не удалось определить длительность фильма или серии")
    count = int(math.ceil(duration / part_duration))
    highlights = []
    for index in range(count):
        start = index * part_duration
        end = min(duration, start + part_duration)
        highlights.append({"title": f"Часть {index + 1:02d}", "start_time": start, "end_time": end, "score": 0})
    shorts = crop_highlights_local(source_path, highlights, aspect_ratio=aspect_ratio, out_dir=out_dir)
    try:
        transcript = transcribe_local(source_path, cache_dir=out_dir)
    except Exception:
        # A movie can legitimately contain no speech. The parts are still useful.
        transcript = {"duration": duration, "segments": []}
    return {"mode": "sequence", "source_video_url": source_path, "duration": duration, "transcript": transcript, "highlights": highlights, "shorts": shorts}
