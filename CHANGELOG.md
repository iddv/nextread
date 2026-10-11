# Changelog

## Unreleased

- Tags are validated, not silently lowercased; write commands print the "lines not understood" warning; non-UTF-8 bytes no longer crash output.
- New settings: `reopen.clear_rating`, `reopen.keep_started`, `next.variety_without_history`, `add.duplicates_check_archive` (each also settable by environment variable; see README).

## 0.1.0

First release.

- Plain-text reading list with a documented line format and lossless round-trip (comments, blank lines, unknown fields, unparseable lines and CRLF are preserved).
- `add`, `edit`, `list`, `show`, `start`, `done`, `drop`, `reopen`, `rm`, `undo`.
- `next`: deterministic ranking with time, tag and type filters and a one-sentence reason.
- `check` / `check --fix`, `open`, `stats`, `export` (csv, json, md), `demo`, `config`, `path`.
- Atomic writes, lock file, conflict detection, undo history with hand-edit detection.
- Settings: `add.duplicates`, `file.done_items`, `next.in_progress`, `write.order`, plus weights, limits and history size.
