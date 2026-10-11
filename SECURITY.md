# Security

## Reporting a problem

Please report security problems privately, using the "Report a vulnerability" button
under the **Security** tab of this repository (GitHub private vulnerability reporting).
Do not open a public issue for a vulnerability. Include the version (`nextread --version`),
what you did and what happened.

## What Nextread does and does not do

- It runs only on your machine, makes **no network access**, and has no accounts, passwords or secrets.
- Access control is the operating system's file permissions. Nextread creates the list, archive,
  config, history and lock files readable and writable by the owner only (mode 0600; directories it
  creates are 0700). Existing files keep the permissions they have.
- `nextread open` runs the program named in `$EDITOR` (or `$VISUAL`, or `vi`) with your list path;
  it trusts those variables the way any command-line tool does.

## Known limits

- Anyone who can read your list file or its `.history` directory can read your reading list and old versions of it. Nothing is encrypted.
- The undo history keeps copies of earlier file contents (the last 50 changes by default), including anything you later deleted by hand, until they are pushed out.
- The lock is a lock file, not an operating-system lock. It stops two Nextread processes from writing at once; it does not stop other programs. Nextread detects such a change and aborts instead (`file changed while working`), but a program that writes between that check and the final rename can still be overwritten.
- A lock left by a crashed process is cleared automatically on Linux and macOS (the process is gone); elsewhere it is cleared after two minutes.
- Hand-edit detection for `undo` uses a hash to notice changes. It is a safety net, not tamper protection.
