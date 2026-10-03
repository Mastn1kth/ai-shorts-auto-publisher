# Project notes

- `--publish-dry-run` skips platform uploads only. Video generation may still call MuAPI, OpenAI or Gemini.
- YouTube/VK `uploaded` means their API accepted a file; it does not confirm processing or public visibility.
- Publishing results are saved one platform at a time in `PUBLISH_LEDGER_FILE`. Keep this file and run publishing sequentially; the current ledger has no cross-process locking.
- Hosted clips use the input source URL plus segment times for duplicate detection. Local clips use a SHA-256 of the rendered file. Recheck this behavior if changing clip boundaries or render output.
- Run `python -m unittest discover -s tests -v` before publishing code changes. Mocked tests verify request flow, not live account permissions or platform processing.
