# Project notes

- `--publish-dry-run` skips platform uploads only. Video generation may still call MuAPI, OpenAI or Gemini.
- YouTube/VK `uploaded` means their API accepted a file; it does not confirm processing or public visibility.
- Publishing results are saved one platform at a time in `PUBLISH_LEDGER_FILE`. Keep this file and run publishing sequentially; the current ledger has no cross-process locking.
- Hosted clips use the input source URL plus segment times for duplicate detection. Local clips use a SHA-256 of the rendered file. Recheck this behavior if changing clip boundaries or render output.
- Run `python -m unittest discover -s tests -v` before publishing code changes. Mocked tests verify request flow, not live account permissions or platform processing.
- Telegram uploads require explicit `--publish-privacy public`, `TELEGRAM_BOT_TOKEN`, and `TELEGRAM_CHAT_ID`; the regular Bot API rejects videos above 50 MB. A Telegram success does not confirm Dzen sync or native Dzen Video publication.
- The Windows desktop entry point is `desktop.py`: pywebview hosts the same local Flask UI in a native WebView2 window. The server binds only to `127.0.0.1` and shuts down with the window. The PyInstaller build must include `web/`, FFmpeg and FFprobe; frozen writable data belongs under `%LOCALAPPDATA%\ShortformStudio`, never under `_MEIPASS`.
- Queued clips are persisted in each `ui-jobs/<id>/job.json` and resumed when the app restarts. Jobs interrupted during generation cannot resume automatically because the per-job LLM key is not persisted. Avoid claiming that scheduling continues while the app is closed.
- On low-space Windows machines, create the virtual environment, pip temporary directory and PyInstaller build directory on a drive with adequate free space. Avoid global `pip install`: a partial installation can break global pydantic/OpenAI until repaired.
