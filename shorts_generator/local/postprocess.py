"""Optional finishing passes for generated vertical clips.

The module deliberately uses the FFmpeg executable already bundled with the
desktop app.  No extra Python media dependency is required for the Windows
build.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path


VIDEO_STYLES = {
    "clean": {"font_size": 54, "primary": "&H00FFFFFF", "outline": "&H00101010", "back": "&H70000000", "alignment": 2, "margin_v": 90},
    "bold": {"font_size": 58, "primary": "&H0000FFFF", "outline": "&H00101010", "back": "&H70000000", "alignment": 2, "margin_v": 100},
    "podcast": {"font_size": 48, "primary": "&H00FFFFFF", "outline": "&H00000000", "back": "&H90000000", "alignment": 8, "margin_v": 120},
    "gaming": {"font_size": 55, "primary": "&H0044FF44", "outline": "&H00FF00FF", "back": "&H70000000", "alignment": 2, "margin_v": 100},
}


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    remainder = seconds - hours * 3600 - minutes * 60
    return f"{hours}:{minutes:02d}:{remainder:05.2f}"


def _ass_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    words = text.split(" ")
    lines = []
    for start in range(0, len(words), 5):
        lines.append(" ".join(words[start:start + 5]))
    return r"\N".join(lines).replace("{", r"\{").replace("}", r"\}")


def write_ass_subtitles(transcript: dict, clip_start: float, clip_end: float, target: Path, style: str = "clean") -> bool:
    """Write segment subtitles clipped to the selected highlight window."""
    preset = VIDEO_STYLES.get(style, VIDEO_STYLES["clean"])
    events = []
    for segment in transcript.get("segments", []):
        start = max(float(segment.get("start", 0)), float(clip_start)) - float(clip_start)
        end = min(float(segment.get("end", 0)), float(clip_end)) - float(clip_start)
        if end <= start or not str(segment.get("text", "")).strip():
            continue
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{_ass_text(segment['text'])}")
    if not events:
        return False
    content = """[Script Info]\nScriptType: v4.00+\nPlayResX: 1080\nPlayResY: 1920\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Arial,{font_size},{primary},&H000000FF,{outline},{back},1,0,0,0,100,100,0,0,1,3,0,{alignment},45,45,{margin_v},1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n{events}\n""".format(events="\n".join(events), **preset)
    target.write_text(content, encoding="utf-8-sig")
    return True


def _duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        )
        return max(0.0, float(result.stdout.strip()))
    except (OSError, ValueError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return 0.0


def _subtitle_filter(path: Path) -> str:
    # FFmpeg filter paths use ':' as a separator, even on Windows.
    value = str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
    return f"subtitles='{value}'"


def enhance_clip(
    source: Path,
    target: Path,
    transcript: dict,
    clip_start: float,
    clip_end: float,
    *,
    style: str = "clean",
    subtitles: bool = True,
    remove_silence: bool = True,
    smooth_edges: bool = True,
    music: Path | None = None,
    music_volume: float = 0.08,
) -> dict:
    """Apply selected finishing passes and return a small diagnostic record."""
    target.parent.mkdir(parents=True, exist_ok=True)
    ass_path = target.with_suffix(".ass")
    has_subtitles = subtitles and write_ass_subtitles(transcript, clip_start, clip_end, ass_path, style)
    duration = _duration(source) or max(0.1, float(clip_end) - float(clip_start))
    fade_duration = min(0.14, duration / 3) if smooth_edges else 0
    video_filters = []
    audio_filters = []
    if has_subtitles:
        video_filters.append(_subtitle_filter(ass_path))
    if smooth_edges and fade_duration:
        video_filters.extend([f"fade=t=in:st=0:d={fade_duration:.3f}", f"fade=t=out:st={max(0, duration - fade_duration):.3f}:d={fade_duration:.3f}"])
        audio_filters.extend([f"afade=t=in:st=0:d={fade_duration:.3f}", f"afade=t=out:st={max(0, duration - fade_duration):.3f}:d={fade_duration:.3f}"])
    if remove_silence:
        audio_filters.insert(0, "silenceremove=start_periods=1:start_duration=0.35:start_threshold=-35dB:stop_periods=1:stop_duration=0.45:stop_threshold=-35dB")
    intermediate = target.with_suffix(".enhanced.mp4") if music and music.is_file() else target
    command = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(source)]
    if video_filters:
        command += ["-vf", ",".join(video_filters)]
    if audio_filters:
        command += ["-af", ",".join(audio_filters)]
    command += ["-map", "0:v:0", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(intermediate)]
    try:
        subprocess.run(command, check=True, capture_output=True, timeout=300)
        music_added = False
        if music and music.is_file() and intermediate.is_file():
            mix = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(intermediate), "-stream_loop", "-1", "-i", str(music), "-filter_complex", f"[1:a]volume={music_volume:.3f}[bg];[0:a][bg]amix=inputs=2:duration=first:dropout_transition=2[a]", "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest", str(target)]
            subprocess.run(mix, check=True, capture_output=True, timeout=300)
            music_added = target.is_file()
            intermediate.unlink(missing_ok=True)
        if ass_path.exists():
            ass_path.unlink(missing_ok=True)
        return {"subtitles": has_subtitles, "music": music_added, "enhanced": target.is_file()}
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        if intermediate != target:
            intermediate.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        return {"subtitles": False, "music": False, "enhanced": False}
