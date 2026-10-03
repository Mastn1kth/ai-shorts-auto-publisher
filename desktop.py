"""Native Windows desktop window for the Shorts studio."""

import os
import sys
from threading import Thread

from werkzeug.serving import make_server

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
    main()
