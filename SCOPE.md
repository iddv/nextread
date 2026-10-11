# Scope: Nextread

Nextread is a command-line reading-list manager for one person who reads a lot. The list lives in a single plain-text file that the user can open and edit by hand at any time. v1 lets them add books, papers, articles and other items in one short command; find, change, start, finish, drop and undo items; validate a hand-edited file; ask "what should I read next?" and get a ranked pick with a one-line reason; and export the list or a monthly reading summary.

## Users

- **Reader (the only role):** one person at their own terminal. They need to capture items in seconds, trust that the file is never corrupted or silently rewritten, and get a useful next pick. There are no accounts, logins or passwords. The person who runs the first command on a machine owns that list. Access is controlled only by the operating system's file permissions on the list file. The tool creates new files as readable and writable by the owner only.

## Core flows

### F1: Install and first run
- Who: Reader
- Steps:
  1. The reader follows the README and runs the single install command on a fresh machine. `nextread` is now on their PATH.
  2. They run `nextread` with no arguments (or `nextread init`).
  3. The system finds no list file at the configured path. It creates the parent directory and the file. The file contains only a header comment that explains the line format with one example line. It also creates the config file with all defaults written out and commented.
  4. The reader sees the list path, the config path, "0 items", and three hint commands: `add`, `demo`, `help`.
  5. Optionally, the reader runs `nextread demo` to load the demo list (see Install and run).
- When it goes wrong:
  - The directory cannot be created or written → the error names the path and the OS reason, and the exit code is non-zero.
  - `demo` is run on a list that already has items → refused with "list not empty; use `--file <new path>`". Nothing changes.
  - The configured file exists but is not a Nextread list (more than 50% of non-blank lines fail to parse) → refused. The tool never overwrites that file.

### F2: Add an item quickly
- Who: Reader
- Steps:
  1. The reader runs `nextread add "<title>"` with optional flags: `--by`, `--type` (book, paper, article, video, other), `--tags a,b`, `--prio 1|2|3`, `--len 300p|25m`, `--url`, `--note`.
  2. If the title argument is a single URL, it becomes the url field, the title is set to the URL, and the type is set to article. No network fetch happens.
  3. The system validates every field, checks for duplicates, assigns an id, sets `added` to today, and appends one line atomically.
  4. The reader sees the stored line and the new id, for example `added k3f9`.
- When it goes wrong:
  - The title is empty or longer than 300 characters, or a field is invalid (bad type, prio outside 1–3, malformed length or URL) → a one-line error names the field and the allowed values. Nothing is written.
  - A duplicate exists (same URL, or the same title ignoring case and punctuation) → handled per `add.duplicates`. The error or warning shows the existing item's id and status.

### F3: List and find items
- Who: Reader
- Steps:
  1. The reader runs `nextread list` with optional filters: `--status`, `--type`, `--tag`, `--prio`, `--search <text>` (matches title, author, note and tags; case-insensitive), and `--sort added|prio|len|title`.
  2. The default shows to-read and reading items, sorted by priority and then by oldest added.
  3. They see one row per item: id, status, prio, type, title, author, length, age in days, and tags. A count is printed at the end.
  4. `nextread show <ref>` prints every field of one item, including unknown fields and the line number in the file.
- When it goes wrong:
  - No item matches → "no items match" with the filters echoed back. Exit code 0.
  - An invalid filter value → an error listing the allowed values.

### F4: Change an item
- Who: Reader
- Steps:
  1. The reader runs `nextread edit <ref>` with any of the F2 flags. `--clear <field>` removes an optional field.
  2. The system resolves the reference (see Domain rules), validates the new values, rewrites only that line, and keeps the rest of the file byte-for-byte.
  3. The reader sees the line before and after the change.
- When it goes wrong:
  - The reference is not found → "no item <ref>".
  - The reference is ambiguous → a list of candidates with their ids. Nothing changes.
  - A value is invalid → the same errors as F2.
  - The file was changed by someone else during the operation → a conflict error (see Money and data integrity).

### F5: Start, finish, drop, reopen and undo
- Who: Reader
- Steps:
  1. The reader runs one of these commands:
     - `nextread start <ref>`: sets status to reading and sets `started` to today.
     - `nextread done <ref> [--rating 1-5] [--note "..."]`: sets status to done and sets `done` to today.
     - `nextread drop <ref> [--note]`: sets status to dropped and sets `dropped` to today.
     - `nextread reopen <ref>`: sets status back to to-read and removes the done or dropped date.
     - `nextread rm <ref>`: deletes the line after a y/N confirmation. `--yes` skips the prompt.
  2. The system checks that the status change is allowed (see Domain rules), records it, and then applies `file.done_items`.
  3. The reader sees the new status. After `done`, they also see days taken (if started) and the count finished this month.
  4. `nextread undo` restores the file to its state before the last Nextread change and prints what was undone. Repeated `undo` steps further back through the history (see Domain rules).
- When it goes wrong:
  - The status change is not allowed (for example `start` on a done item) → the error suggests `reopen`.
  - The rating is outside 1–5 → an error.
  - There is nothing to undo → "nothing to undo".
  - The file was edited outside Nextread since the change being undone → refused with "file edited since; use `--force`". `--force` restores anyway, and the current content is saved to history first.

### F6: What to read next
- Who: Reader
- Steps:
  1. The reader runs `nextread next` with optional flags: `--time 30m` (time available now), `--tag x`, `--type y`, `--count N` (1–10, default 1), and `--why` (show the full score breakdown).
  2. The system scores every to-read item, and reading items according to `next.in_progress`, using the rules in Domain rules. It is deterministic: the same file, date and flags give the same answer.
  3. For each pick, the reader sees the id, title, author, length and a one-sentence reason built from the two largest score factors, for example: "Priority 1, waiting 6 weeks, and it fits your 30 minutes."
  4. They can act on the pick directly with `nextread start <id>`.
- When it goes wrong:
  - The list is empty, or no items match the filters → "nothing to read; add something with `nextread add`".
  - Nothing fits `--time` → the shortest matching items are shown instead, with the reason "nothing fits 30m; this is the shortest".

### F7: Hand-edit and check the file
- Who: Reader
- Steps:
  1. The reader runs `nextread open` (opens `$EDITOR`, falling back to `vi`) or edits the file with any editor.
  2. After `open` closes, or when the reader runs `nextread check`, the system parses the whole file.
  3. It reports each problem with its line number, the line text and the reason. Examples: unknown status marker, bad prio, bad date, duplicate id, done item without a done date.
  4. `nextread check --fix` makes only safe repairs:
     - assigns ids to item lines that lack one;
     - adds a missing `added` date (today);
     - normalises the order of field keys.
     It reports each repair. Lines it cannot parse are never changed.
  5. The reader sees "N items, 0 problems", or a list of the problems.
- When it goes wrong:
  - There are unparseable lines → every other command still works. Those lines are kept verbatim, and each command prints a one-line warning: "2 lines not understood; run `nextread check`".
  - A duplicate id → `--fix` gives the later line a new id and reports it.

### F8: Monthly summary and export
- Who: Reader
- Steps:
  1. The reader runs `nextread stats [--month 2026-10 | --year 2026]`. The default is the current month.
  2. They see:
     - items added and finished in the period;
     - finished items by type;
     - pages and minutes finished;
     - average days from start to done;
     - dropped count;
     - the current to-read backlog size;
     - the 3 oldest waiting items.
  3. The reader runs `nextread export --format csv|json|md [--status ...] [--from DATE --to DATE] [--out path]`. The `--from` and `--to` dates filter on the `done` date for done items and on `added` for the rest.
  4. The system writes every matching item with all fields, including unknown ones. JSON uses one object per item. CSV has a fixed header followed by an `extra` column. Markdown is a checklist grouped by status. Output goes to stdout or to the `--out` file.
  5. The reader sees the export, or "exported N items to <path>".
- When it goes wrong:
  - A bad month or date format → an error showing the expected format.
  - The `--out` file already exists → refused unless `--force` is given.
  - The `--out` path cannot be written → an error with the OS reason.

## Features

### Must have (v1)
- M1: Single-command install, auto-created empty list and commented config, `demo` command (F1)
- M2: Documented line-based file format with lossless round-trip, so comments, blank lines, unknown fields and unparseable lines are preserved verbatim (F1–F8)
- M3: `add` with field validation, URL-only shortcut, and duplicate detection (F2)
- M4: `list` with filters, search and sort; `show` for one item (F3)
- M5: Item references by id or unique title substring, with an ambiguity report (F3–F6)
- M6: `edit` and `--clear` that rewrite one line only (F4)
- M7: Status transitions `start`, `done`, `drop`, `reopen` and `rm`, plus the done-items policy (F5)
- M8: Undo history of snapshots with hand-edit detection (F5)
- M9: Deterministic `next` ranking with time, tag and type filters and generated reasons (F6)
- M10: `open` and `check` / `check --fix` with line-numbered diagnostics (F7)
- M11: `stats` per month or year, and `export` to CSV, JSON and Markdown (F8)
- M12: Atomic writes, a lock, conflict detection, and an automated test suite (all flows)

### Later (not in v1)
- Fetching titles and metadata from URLs, DOIs or ISBNs: needs network access and error handling, and manual entry works.
- Browser extension or tab import: integration work outside the terminal.
- AI-generated recommendations: the deterministic ranking with reasons meets the need and is testable.
- Sync across devices: the user can keep the plain file in their own synced folder.
- Multiple lists or profiles: `--file` already covers this.
- Reading-progress tracking (current page) and reminders: nice to have, not needed for picking and finishing.
- Interactive full-screen UI: the command set is enough.

## Domain rules and defaults

**Line format.** Each item is one line. Fields are separated by ` | `, and the first field is the status marker followed by the title:
`[ ] Designing Data-Intensive Applications | by: Martin Kleppmann | type: book | tags: systems, db | prio: 1 | len: 600p | url: https://… | added: 2026-10-01 | id: k3f9`

**Status markers:**
- `[ ]` to-read
- `[>]` reading
- `[x]` done
- `[-]` dropped

**Other lines.** A line starting with `#` is a comment. Blank lines and comments are kept. A literal `|` in a value is written as `\|`.

**Fields and limits:**
- Known keys: `by`, `type`, `tags`, `prio`, `len`, `url`, `note`, `added`, `started`, `done`, `dropped`, `rating`, `id`.
- Keys are case-insensitive. Unknown keys are kept as they are.
- Title: 1–300 characters (default limit).
- Note: up to 500 characters (default).
- Tags: lowercase letters, digits and hyphens, at most 10 per item (default).
- Types: book, paper, article, video, other. The default type is article.
- `prio` is 1 (high), 2 or 3. The default is 2.
- `len` is a whole number of pages (`p`) or minutes (`m`), from 1 to 5000.
- `rating` is 1–5. It is allowed only on done items.
- Dates are `YYYY-MM-DD` in the local time zone. "Today" means the machine's local date.

**Ids.** An id is 4 lowercase base-36 characters, random, and unique within the file. If an id is taken, a new one is drawn.

**References.** A reference resolves in this order:
1. an exact id;
2. an exact title, ignoring case;
3. a unique case-insensitive substring of the title.

If more than one item matches, the command lists the candidates and stops.

**Status transitions:**
- to-read → reading, done or dropped
- reading → done, dropped or to-read
- done or dropped → to-read, only through `reopen`

**Duplicates.** Two items are duplicates if they have the same URL after trimming and removing a trailing slash, or the same title after lowercasing and removing punctuation and whitespace runs.

**Length estimates:**
- 1 page = 2 minutes (default).
- When `len` is missing, the estimate is: article 15m, paper 45m, video 30m, book 600m, other 30m (defaults).

**`next` scoring** (all weights are defaults):
- Priority: prio 1 = 30, prio 2 = 15, prio 3 = 0.
- Waiting: 1 point per full week since `added`, capped at 20.
- In progress: +25 for reading items when `next.in_progress` = prefer.
- Time: with `--time`, items whose estimate fits get +20, and items that don't fit are excluded.
- Variety: +10 if the item's type differs from the type of the most recently finished item.
- Ties are broken by the oldest `added`, then by line order.
- The reason sentence names the two largest non-zero factors, plus the time fit when `--time` was given.

**Undo history:**
- Before each write, Nextread stores a snapshot of the previous file content.
- It keeps the last 50 snapshots (default), each with the command that caused the change.
- Each write also records a hash of the file it produced. Hand-edit detection compares the current file's hash with that recorded hash.

**Statistics.** Pages and minutes are counted from `len` (minutes use the page conversion above). Items without `len` are counted, but contribute no pages or minutes, and the output says how many such items there are.

## Operator settings

| key | values | default | what it decides |
|---|---|---|---|
| `add.duplicates` | reject, warn | reject | Whether adding a duplicate is refused or saved with a warning. |
| `file.done_items` | keep, archive | keep | Whether done and dropped items stay in the list file or are moved to a sibling archive file (`<name>.archive.txt`); list, stats and export read both files. |
| `next.in_progress` | prefer, ignore | prefer | Whether items already being read are favoured by `next` or left out of its picks. |
| `write.order` | preserve, sort | preserve | Whether Nextread appends new items and keeps the hand-made order, or rewrites item lines in status/priority/added order (comments stay at the top). |

## Money and data integrity

Nextread handles no money.

**Never lose or double-count:**
- No reader-written content is ever lost. Comments, blank lines, unknown fields and unparseable lines survive every command unchanged.
- Each command changes only the lines it targets. The exception is `write.order` = sort.
- Each item is counted once in list, stats and export, including when an archive file is in use. An id found in both files is reported by `check`.

**Writes:**
- Every write goes to a temporary file in the same directory, is flushed, and is then atomically renamed over the original. A crash leaves either the old file or the new one, never a partial file.
- The file's permissions are preserved.
- Line endings are preserved: if the file used CRLF, it keeps CRLF.

**Concurrency:**
- Writers hold an exclusive lock file for the whole read-modify-write.
- A second Nextread process waits up to 5 seconds (default), then fails with "list is busy".
- Before renaming, Nextread re-reads the file. If its content differs from what was read (for example, an editor saved meanwhile), the write is aborted with "file changed while working; nothing written, run again".

**Validation:** all input is validated before anything is written, and a failed command writes nothing.

## Install and run

- **Install:** one documented command installs Nextread on a fresh machine and puts `nextread` on the PATH. The README also gives the uninstall command, and states that uninstalling does not delete the reader's data.
- **Safe defaults:**
  - A fresh install starts with an empty list.
  - There are no accounts or secrets.
  - Nextread makes no network access of any kind.
  - Files are created with owner-only permissions.
- **Demo data:**
  - `nextread demo [--file path]` loads about 40 realistic items:
    - 15 books, 10 papers, 12 articles and 3 videos;
    - all four statuses;
    - added dates spread over the past 6 months;
    - finished dates in this month and the previous two;
    - a mix of priorities, tags, lengths and ratings;
    - two comment lines;
    - one deliberately malformed line, so `check` has something to report.
  - Demo data is loaded only by this command, and only into an empty or new file.
- **Configuration:**
  - The list path defaults to the platform's user data directory (`~/.local/share/nextread/reading.txt` on Linux). The README states the equivalents for other platforms.
  - It can be overridden, in order of precedence, by `--file`, the `NEXTREAD_FILE` environment variable, or `file` in the config file.
  - The config file is at the platform's user config directory (`~/.config/nextread/config` on Linux) and can be overridden by `NEXTREAD_CONFIG`. It holds the four settings and the defaults marked above (weights, limits, page minutes, history size).
  - `nextread config` shows the effective values and where each came from. `nextread config set <key> <value>` validates and saves a value.
  - Every option is documented in the README.
- **Data, backup and restore:**
  - Everything lives in the list file, the optional archive file, and the history directory next to them.
  - Backup means copying the list file (and the archive file). Restore means copying it back. `nextread path` prints all locations.
- **Upgrades:**
  - The header comment carries `format: 1`. Future versions read older formats and upgrade the header on the next write.
  - A file with a newer format than the installed tool understands is opened read-only, with a warning.

## Non-functional basics

- **Access:** single user, no authentication. File permissions are the access control.
- **Errors:**
  - Every error is one plain line naming the field or line, and the exit code is non-zero.
  - Exit codes: 0 means success, 1 means a usage or validation error, 2 means a conflict or busy file, 3 means an I/O error.
  - `--help` on every command lists its flags with examples.
- **Persistence and recovery:** all state is in plain files and survives restarts. Undo history is kept as described in Domain rules.
- **Speed:** a 5,000-item list (default reference size) loads, lists and ranks in under 1 second.
- **Tests:**
  - An automated suite runs with one documented command.
  - It covers:
    - parse/write round-trips, including comments, unknown fields, malformed lines and CRLF;
    - every command's success and failure cases;
    - ranking and reason text with a fixed date;
    - undo and hand-edit detection;
    - the lock and conflict abort;
    - the archive setting;
    - the stats totals and all three export formats.

## Definition of done

- [ ] F1: Install and first run — on a fresh machine, the README command plus `nextread` prints the new list path, "0 items" and hints; the file contains only the header; `nextread demo` then lists about 40 items.
- [ ] F2: Add an item quickly — `nextread add "Title" --type book --prio 1` prints a new id, and the line appears at the end of the file; repeating the command is rejected as a duplicate that names the first item's id.
- [ ] F3: List and find items — `nextread list --tag systems --search kleppmann` shows only the matching rows with a correct count; `show <id>` prints every field and the line number.
- [ ] F4: Change an item — `nextread edit <ref> --prio 3` shows the before and after lines, and a diff of the file shows exactly one changed line.
- [ ] F5: Start, finish, drop, reopen and undo — `start`, then `done --rating 4`, sets the dates and status in the file; `undo` restores the previous line exactly; `undo` after a hand edit is refused without `--force`.
- [ ] F6: What to read next — `nextread next --time 30m --count 3` shows three items that each fit within 30 minutes, each with a reason sentence, and the same output on a repeat run.
- [ ] F7: Hand-edit and check the file — after a hand-added line without an id and one malformed line, `check` reports both with line numbers; `check --fix` adds the id and leaves the malformed line untouched.
- [ ] F8: Monthly summary and export — `nextread stats --month <current>` shows totals that match the done items in the file; `export --format csv --out f.csv` writes every item with a header row.
