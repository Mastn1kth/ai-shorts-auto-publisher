import tempfile
import unittest
from pathlib import Path

from shorts_generator.local.postprocess import write_ass_subtitles


class PostprocessTests(unittest.TestCase):
    def test_ass_subtitles_are_clipped_and_styled(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "clip.ass"
            ok = write_ass_subtitles(
                {"segments": [{"start": 4, "end": 8, "text": "Первое второе третье четвертое пятое шестое"}]},
                5, 10, target, "bold",
            )
            self.assertTrue(ok)
            content = target.read_text(encoding="utf-8-sig")
            self.assertIn("Style: Default,Arial,58", content)
            self.assertIn("0:00:00.00,0:00:02.50", content)
            self.assertIn(r"{\k50}Первое", content)

    def test_empty_transcript_does_not_create_subtitles(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "clip.ass"
            self.assertFalse(write_ass_subtitles({"segments": []}, 0, 10, target))
            self.assertFalse(target.exists())
