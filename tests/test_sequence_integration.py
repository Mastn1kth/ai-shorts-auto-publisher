"""Opt-in media pipeline smoke test with a tiny generated source video."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from shorts_generator.local.sequence import build_sequential_parts, media_duration


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is unavailable")
class SequenceIntegrationTests(unittest.TestCase):
    def test_local_video_becomes_consecutive_vertical_parts(self):
        try:
            import cv2  # noqa: F401
        except ImportError:
            self.skipTest("OpenCV is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.mp4"
            subprocess.run([
                "ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
                "-i", "testsrc2=size=320x180:rate=10:duration=2.2",
                "-f", "lavfi", "-i", "sine=frequency=440:duration=2.2",
                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(source),
            ], check=True, timeout=60)
            with patch("shorts_generator.local.sequence.transcribe_local", return_value={"segments": []}):
                result = build_sequential_parts(str(source), part_duration=2, out_dir=directory)
            shorts = result["shorts"]
            self.assertEqual(len(shorts), 2)
            self.assertEqual([(part["start_time"], part["end_time"]) for part in shorts],
                             [(0, 2), (2, result["duration"])])
            for part in shorts:
                self.assertIsNone(part.get("error"))
                self.assertTrue(Path(part["clip_url"]).is_file())
                self.assertGreater(media_duration(part["clip_url"]), 0)


if __name__ == "__main__":
    unittest.main()
