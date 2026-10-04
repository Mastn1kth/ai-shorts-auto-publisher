"""Desktop bootstrap should tolerate Windows legacy output encodings."""

import io
import unittest
from unittest.mock import patch

import desktop


class DesktopOutputTests(unittest.TestCase):
    def test_non_ascii_video_title_does_not_abort_logging(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1252")
        with patch.object(desktop.sys, "stdout", stream):
            desktop._configure_output()
            print("Part 1 → Глава")
            stream.flush()
        self.assertIn(b"\\u2192", raw.getvalue())
        self.assertIn(b"\\u0413", raw.getvalue())


if __name__ == "__main__":
    unittest.main()
