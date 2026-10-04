"""Native Windows desktop window for the Shorts studio."""

import os
import sys
import traceback
from pathlib import Path
from threading import Thread

from werkzeug.serving import make_server


def _configure_output() -> None:
    # Windowed Windows builds may inherit a legacy console encoding. Titles and
    # paths from YouTube must never abort a video job when logged.
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="backslashreplace")


_configure_output()

from web_app import app, restore_jobs


def main() -> None:
    import webview  # type: ignore

    if getattr(sys, "frozen", False):
        os.environ["PATH"] = str(sys._MEIPASS) + os.pathsep + os.environ.get("PATH", "")
    restore_jobs()
    server = make_server("127.0.0.1", 0, app, threaded=True)
    Thread(target=server.serve_forever, daemon=True).start()
    try:
        webview.create_window(
            "Shortform Studio",
            f"http://127.0.0.1:{server.server_port}/",
            width=1440,
            height=900,
            min_size=(900, 640),
            background_color="#0b0d0c",
        )
        webview.start(gui="edgechromium", debug=False)
    finally:
        server.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_dir = Path(os.getenv("LOCALAPPDATA", Path.cwd())) / "ShortformStudio"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "startup-error.log"
        log_file.write_text(traceback.format_exc(), encoding="utf-8")
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.user32.MessageBoxW(
                None,
                f"Не удалось запустить Shortform Studio. Подробности: {log_file}",
                "Shortform Studio", 0x10,
            )
        raise
