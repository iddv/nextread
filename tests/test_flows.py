"""End-to-end tests of every flow in the definition of done, through the real CLI."""
import csv
import io
import json
import os
import stat
import unittest

from helpers import CliCase, TODAY


class F1InstallAndFirstRun(CliCase):
    def test_first_run_creates_header_only_list_and_config(self):
        out = self.ok()
        self.assertIn(self.list, out)
        self.assertIn(self.config, out)
        self.assertIn("0 items", out)
        for hint in ("nextread add", "nextread demo", "nextread help"):
            self.assertIn(hint, out)
        lines = self.read().splitlines()
        self.assertTrue(lines and all(l.startswith("#") for l in lines))
        self.assertTrue(any("format: 1" in l for l in lines))
        self.assertTrue(any(l.startswith("# Example:") and "[ ]" in l for l in lines))
        cfg = self.read(self.config)
        for key in ("add.duplicates", "file.done_items", "next.in_progress", "write.order", "history.size", "limits.title"):
            self.assertIn("# %s = " % key, cfg)
        for p in (self.list, self.config):
            self.assertEqual(stat.S_IMODE(os.stat(p).st_mode), 0o600)

    def test_init_is_repeatable_and_keeps_content(self):
        self.ok("init")
        self.add("Keep me")
        before = self.read()
        out = self.ok("init")
        self.assertIn("1 item", out)
        self.assertEqual(self.read(), before)

    def test_demo_loads_about_forty_items(self):
        self.ok()
        self.ok("demo")
        rows = json.loads(self.ok("export", "--format", "json"))
        self.assertEqual(len(rows), 40)
        types = {}
        for r in rows:
            types[r["type"]] = types.get(r["type"], 0) + 1
        self.assertEqual(types, {"book": 15, "paper": 10, "article": 12, "video": 3})
        self.assertEqual({r["status"] for r in rows}, {"to-read", "reading", "done", "dropped"})
        text = self.read()
        self.assertEqual(len([l for l in text.splitlines() if l.startswith("# Demo") or l.startswith("# A deliberately")]), 2)
        # finished dates fall in this month and the previous two
        months = {r["done"][:7] for r in rows if r["done"]}
        self.assertEqual(months, {"2026-10", "2026-09", "2026-08"})
        rc, out, err = self.run_cli("check")
        self.assertEqual(rc, 1)
        self.assertIn("unknown status marker", out)
        self.assertIn("40 items, 1 problem", out)
        self.assertGreater(len(self.ok("list").splitlines()), 20)

    def test_demo_refused_when_list_not_empty(self):
        self.add("Something")
        before = self.read()
        err = self.err("demo")
        self.assertIn("list not empty; use `--file <new path>`", err)
        self.assertEqual(self.read(), before)

    def test_demo_into_new_file(self):
        other = os.path.join(self.tmp, "other.txt")
        self.ok("demo", "--file", other)
        self.assertEqual(self.ok("list", "--file", other, "--status", "all").strip().splitlines()[-1], "40 items")

    def test_refuses_file_that_is_not_a_list(self):
        prose = "Dear diary,\ntoday was long.\nI did nothing.\n[ ] one item | id: aa11\n"
        self.write(prose)
        for cmd in (["add", "x"], ["demo"], ["init"], ["list"]):
            err = self.err(*cmd)
            self.assertIn("does not look like a Nextread list", err)
        self.assertEqual(self.read(), prose)

    def test_unwritable_directory_names_path_and_exit_3(self):
        blocker = os.path.join(self.tmp, "blocker")
        open(blocker, "w").close()
        bad = os.path.join(blocker, "sub", "reading.txt")
        err = self.err("init", "--file", bad, code=3)
        self.assertIn(blocker, err)
        self.assertTrue(err.count("\n") == 1)


class F2Add(CliCase):
    def test_add_prints_line_and_id_and_appends(self):
        out = self.ok("add", "Designing Data-Intensive Applications", "--type", "book", "--prio", "1")
        new_id = out.strip().splitlines()[-1]
        self.assertRegex(new_id, r"^added [0-9a-z]{4}$")
        last = self.read().splitlines()[-1]
        self.assertEqual(last, "[ ] Designing Data-Intensive Applications | type: book | prio: 1 | added: %s | id: %s" % (TODAY, new_id.split()[1]))
        self.assertIn(last, out)
        err = self.err("add", "Designing Data-Intensive Applications", "--type", "book", "--prio", "1")
        self.assertIn(new_id.split()[1], err)
        self.assertIn("to-read", err)

    def test_all_flags(self):
        i = self.add("Full", "--by", "Me", "--type", "paper", "--tags", "a,b-c", "--prio", "3", "--len", "25m",
                     "--url", "https://x.org/p", "--note", "n | with pipe")
        line = self.read().splitlines()[-1]
        self.assertIn("by: Me | type: paper | tags: a, b-c | prio: 3 | len: 25m | url: https://x.org/p | note: n \\| with pipe", line)
        self.assertIn("note:    n | with pipe", self.ok("show", i))

    def test_url_shortcut(self):
        self.ok("add", "https://example.com/post")
        line = self.read().splitlines()[-1]
        self.assertTrue(line.startswith("[ ] https://example.com/post | type: article | url: https://example.com/post"))

    def test_duplicates_by_url_and_title(self):
        self.ok("add", "https://example.com/post")
        self.assertIn("duplicate", self.err("add", "https://example.com/post/"))
        self.add("Hello, World!")
        self.assertIn("duplicate", self.err("add", "hello   world"))
        self.assertIn("duplicate", self.err("add", "Other title", "--url", "https://example.com/post"))

    def test_duplicates_warn_mode(self):
        self.add("Same")
        self.ok("config", "set", "add.duplicates", "warn")
        rc, out, err = self.run_cli("add", "same")
        self.assertEqual(rc, 0)
        self.assertIn("duplicate", err)
        self.assertEqual(len(json.loads(self.ok("export", "--format", "json"))), 2)

    def test_validation_errors_write_nothing(self):
        self.ok()
        before = self.read()
        cases = [
            (["add", ""], "title"),
            (["add", "x" * 301], "300"),
            (["add", "T", "--type", "film"], "book, paper, article, video, other"),
            (["add", "T", "--prio", "4"], "1, 2 or 3"),
            (["add", "T", "--len", "12x"], "len"),
            (["add", "T", "--len", "5001p"], "5000"),
            (["add", "T", "--url", "not a url"], "url"),
            (["add", "T", "--tags", "Bad Tag"], "tags"),
            (["add", "T", "--note", "n" * 501], "500"),
        ]
        for args, needle in cases:
            err = self.err(*args)
            self.assertIn(needle, err)
            self.assertEqual(err.count("\n"), 1, err)
        self.assertEqual(self.read(), before)


class F3ListAndFind(CliCase):
    def setUp(self):
        super().setUp()
        self.k = self.add("Designing Data-Intensive Applications", "--by", "Martin Kleppmann", "--type", "book", "--tags", "systems,db", "--prio", "1", "--len", "600p")
        self.add("Systems Performance", "--by", "Brendan Gregg", "--type", "book", "--tags", "systems", "--prio", "2")
        self.add("Poetry", "--type", "other", "--prio", "3", "--note", "mentions Kleppmann once")

    def test_filter_and_search(self):
        out = self.ok("list", "--tag", "systems", "--search", "kleppmann")
        self.assertIn("Designing Data", out)
        self.assertNotIn("Systems Performance", out)
        self.assertTrue(out.strip().endswith("1 item"))
        out = self.ok("list", "--search", "KLEPPMANN")
        self.assertTrue(out.strip().endswith("2 items"))

    def test_default_sort_prio_then_oldest(self):
        rows = self.ok("list").splitlines()[1:-1]
        self.assertEqual([r.split()[2] for r in rows], ["1", "2", "3"])

    def test_sort_options(self):
        rows = self.ok("list", "--sort", "title").splitlines()[1:-1]
        self.assertIn("Designing", rows[0])
        rows = self.ok("list", "--sort", "len").splitlines()[1:-1]
        self.assertIn("Poetry", rows[0])

    def test_no_match_and_bad_filters(self):
        out = self.ok("list", "--tag", "nothing")
        self.assertIn("no items match", out)
        self.assertIn("tag=nothing", out)
        self.assertIn("book, paper, article, video, other", self.err("list", "--type", "film"))
        self.assertIn("to-read", self.err("list", "--status", "bogus"))
        self.assertIn("choose from 'added', 'prio', 'len', 'title'", self.err("list", "--sort", "x"))

    def test_status_filter_default_hides_done(self):
        self.ok("done", self.k)
        self.assertNotIn("Designing", self.ok("list"))
        self.assertIn("Designing", self.ok("list", "--status", "done"))
        self.assertIn("Designing", self.ok("list", "--status", "all"))

    def test_show_all_fields_and_line_number(self):
        text = self.read()
        self.write(text.replace("\n[ ] Poetry", "\n[ ] Poetry | colour: blue").replace("| note: mentions", "| note: mentions"))
        out = self.ok("show", "poetry")
        self.assertIn("colour:  blue", out)
        n = [i for i, l in enumerate(self.read().splitlines(), 1) if "Poetry" in l][0]
        self.assertIn("line:    %d" % n, out)
        out = self.ok("show", self.k)
        for needle in ("by:", "Martin Kleppmann", "600p", "systems, db", "added:", "id:"):
            self.assertIn(needle, out)

    def test_references(self):
        self.assertIn("Poetry", self.ok("show", "POETRY"))
        self.assertIn("no item zzz", self.err("show", "zzz"))
        err = self.err("show", "s")  # substring of two titles
        self.assertIn("matches 2 items", err)
        self.assertIn(self.k, err)


class F4Edit(CliCase):
    def test_edit_one_line_only(self):
        self.write("# top\n\n[ ] Alpha | prio: 1 | id: aa11\n[ ] Beta | colour: red | id: bb22\nnot understood\n")
        before = self.read().splitlines()
        out = self.ok("edit", "beta", "--prio", "3")
        self.assertIn("before: [ ] Beta | colour: red | id: bb22", out)
        self.assertIn("after:  [ ] Beta | prio: 3 | colour: red | id: bb22", out)
        after = self.read().splitlines()
        self.assertEqual(len(before), len(after))
        self.assertEqual([i for i in range(len(before)) if before[i] != after[i]], [3])

    def test_clear_and_title(self):
        i = self.add("Gamma", "--url", "https://a.b/c", "--prio", "1")
        self.ok("edit", i, "--clear", "url", "--clear", "prio", "--title", "Gamma 2")
        line = self.read().splitlines()[-1]
        self.assertTrue(line.startswith("[ ] Gamma 2 | added:"), line)
        self.assertNotIn("url", line)
        self.assertIn("cannot clear", self.err("edit", i, "--clear", "id"))

    def test_errors(self):
        a = self.add("Alpha one")
        self.add("Alpha two")
        self.assertIn("no item nope", self.err("edit", "nope", "--prio", "1"))
        err = self.err("edit", "alpha", "--prio", "1")
        self.assertIn("matches 2 items", err)
        self.assertIn("1, 2 or 3", self.err("edit", a, "--prio", "0"))
        self.assertIn("nothing to change", self.err("edit", a))
        self.assertIn("rating is only allowed on done", self.err("edit", a, "--rating", "3"))
        self.assertIn("duplicate", self.err("edit", a, "--title", "alpha TWO"))

    def test_no_change_writes_nothing(self):
        i = self.add("Same", "--prio", "2")
        before = self.read()
        self.assertIn("no change", self.ok("edit", i, "--prio", "2"))
        self.assertEqual(self.read(), before)


class F5Transitions(CliCase):
    def test_start_done_undo(self):
        i = self.add("Book", "--type", "book")
        added = self.read().splitlines()[-1]
        self.ok("start", i)
        self.assertIn("started: %s" % TODAY, self.read())
        self.assertIn("[>]", self.read())
        started_line = self.read().splitlines()[-1]
        out = self.ok("done", i, "--rating", "4", "--note", "good")
        self.assertIn("finished this month: 1", out)
        self.assertIn("took 0 days", out)
        line = self.read().splitlines()[-1]
        self.assertTrue(line.startswith("[x] Book"))
        self.assertIn("done: %s" % TODAY, line)
        self.assertIn("rating: 4", line)
        self.assertIn("note: good", line)
        self.ok("undo")
        self.assertEqual(self.read().splitlines()[-1], started_line)
        self.ok("undo")
        self.assertEqual(self.read().splitlines()[-1], added)

    def test_days_taken(self):
        self.write("[>] Long | started: 2026-10-01 | added: 2026-09-01 | id: aa11\n")
        self.assertIn("took 10 days", self.ok("done", "aa11"))

    def test_invalid_transitions_suggest_reopen(self):
        i = self.add("X")
        self.ok("done", i)
        for cmd in ("start", "drop", "done"):
            err = self.err(cmd, i)
            self.assertIn("reopen", err)
        self.ok("reopen", i)
        self.assertIn("[ ]", self.read().splitlines()[-1])
        self.assertNotIn("done:", self.read().splitlines()[-1])
        self.assertIn("already", self.err("reopen", i))
        self.ok("start", i)
        self.assertIn("already reading", self.err("start", i))
        self.ok("reopen", i)
        self.assertIn("started", self.read().splitlines()[-1])  # reopen.keep_started defaults to true

    def test_bad_rating(self):
        i = self.add("X")
        before = self.read()
        self.assertIn("rating", self.err("done", i, "--rating", "6"))
        self.assertIn("rating", self.err("done", i, "--rating", "x"))
        self.assertEqual(self.read(), before)

    def test_drop_and_reopen_removes_rating_and_dates(self):
        i = self.add("X")
        self.ok("drop", i, "--note", "meh")
        line = self.read().splitlines()[-1]
        self.assertTrue(line.startswith("[-]"))
        self.assertIn("dropped: %s" % TODAY, line)
        self.ok("reopen", i)
        self.assertNotIn("dropped", self.read().splitlines()[-1])

    def test_rm_warns_about_bad_lines_once(self):
        i = self.add("Doomed")
        with open(self.list, "a") as fh:
            fh.write("junk1\njunk2\n")
        rc, out, err = self.run_cli("rm", i, "--yes")
        self.assertEqual(rc, 0)
        self.assertEqual(err.count("2 lines not understood"), 1, err)
        i = self.add("Second")
        rc, out, err = self.run_cli("rm", i, input="y\n")
        self.assertEqual(err.count("lines not understood"), 1, err)

    def test_rm_confirmation(self):
        i = self.add("Doomed")
        keep = self.add("Keeper")
        rc, out, err = self.run_cli("rm", i, input="n\n")
        self.assertEqual(rc, 1)
        self.assertIn("Doomed", self.read())
        rc, out, err = self.run_cli("rm", i, input="")
        self.assertEqual(rc, 1)
        self.assertIn("Doomed", self.read())
        self.ok("rm", i, input="y\n")
        self.assertNotIn("Doomed", self.read())
        self.ok("rm", keep, "--yes")
        self.assertNotIn("Keeper", self.read())

    def test_undo_refused_after_hand_edit_unless_forced(self):
        i = self.add("Edited")
        self.ok("start", i)
        text = self.read()
        edited = text + "# a hand-made note\n"
        self.write(edited)
        err = self.err("undo", code=2)
        self.assertIn("file edited since; use `--force`", err)
        self.assertEqual(self.read(), edited)
        out = self.ok("undo", "--force")
        self.assertIn("saved", out)
        self.assertNotIn("started:", self.read())
        saved_dir = self.list + ".history/saved"
        saved = [os.path.join(saved_dir, n) for n in os.listdir(saved_dir)]
        self.assertEqual(len(saved), 1)
        self.assertEqual(self.read(saved[0]), edited)

    def test_nothing_to_undo(self):
        self.ok()
        self.assertIn("nothing to undo", self.err("undo"))

    def test_undo_walks_back_through_history(self):
        self.ok()
        base = self.read()
        a = self.add("A")
        one = self.read()
        self.add("B")
        self.ok("undo")
        self.assertEqual(self.read(), one)
        self.ok("undo")
        self.assertEqual(self.read(), base)
        self.err("undo")

    def test_history_is_limited(self):
        self.ok("config", "set", "history.size", "3")
        for n in range(6):
            self.add("Item %d" % n)
        for _ in range(3):
            self.ok("undo")
        self.err("undo")
        self.assertEqual(len(self.ok("list").splitlines()), 1 + 3 + 1)


class F6Next(CliCase):
    def test_reason_text_with_fixed_date(self):
        self.write("[ ] Waiting | prio: 1 | len: 20m | added: 2026-08-30 | id: aa11\n")
        out = self.ok("next", "--time", "30m")
        self.assertIn("1. aa11  Waiting", out)
        self.assertIn("Priority 1, waiting 6 weeks, and it fits your 30 minutes.", out)
        self.assertIn("nextread start aa11", out)

    def test_time_count_and_determinism(self):
        self.ok("demo")
        out = self.ok("next", "--time", "30m", "--count", "3")
        self.assertEqual(out, self.ok("next", "--time", "30m", "--count", "3"))
        picks = [l for l in out.splitlines() if l[:2] in ("1.", "2.", "3.")]
        self.assertEqual(len(picks), 3)
        self.assertEqual(len([l for l in out.splitlines() if l.startswith("   ") and l.strip().endswith(".")]), 3)
        ids = [l.split()[1] for l in picks]
        rows = {r["id"]: r for r in json.loads(self.ok("export", "--format", "json"))}
        for i in ids:
            n, unit = int(rows[i]["len"][:-1]), rows[i]["len"][-1]
            self.assertLessEqual(n * (2 if unit == "p" else 1), 30)

    def test_scoring_components(self):
        self.write(
            "[x] Last | type: book | done: 2026-10-01 | added: 2026-09-01 | id: dd44\n"
            "[ ] Old low | type: book | prio: 3 | added: 2026-01-01 | id: aa11\n"
            "[ ] New high | type: paper | prio: 1 | added: 2026-10-10 | id: bb22\n"
            "[>] Reading | type: book | prio: 3 | added: 2026-10-10 | id: cc33\n")
        out = self.ok("next", "--count", "3", "--why")
        self.assertEqual([l.split()[1] for l in out.splitlines() if l[:2] in ("1.", "2.", "3.")], ["bb22", "cc33", "aa11"])
        self.assertIn("Priority 1 and a change from your last book.", out)
        self.assertIn("score 40 = priority 30 + in progress 0 + waiting 0 + variety 0 + time fit 0".replace("variety 0", "variety 10"), out)
        self.assertIn("Waiting 40 weeks.", out)

    def test_in_progress_prefer_and_ignore(self):
        self.write("[>] Reading | prio: 3 | added: 2026-10-10 | id: cc33\n[ ] Other | prio: 3 | added: 2026-10-10 | id: aa11\n")
        self.assertIn("1. cc33", self.ok("next"))
        self.assertIn("Already in progress", self.ok("next"))
        self.ok("config", "set", "next.in_progress", "ignore")
        out = self.ok("next", "--count", "2")
        self.assertIn("1. aa11", out)
        self.assertNotIn("cc33", out)

    def test_variety_bonus_and_tie_break(self):
        self.write(
            "[x] Last | type: book | done: 2026-10-01 | added: 2026-09-01 | id: dd44\n"
            "[ ] Same type | type: book | prio: 2 | added: 2026-10-10 | id: aa11\n"
            "[ ] Other type | type: paper | prio: 2 | added: 2026-10-10 | id: bb22\n")
        out = self.ok("next")
        self.assertIn("1. bb22", out)
        self.assertIn("a change from your last book", out)
        # equal scores: oldest added wins, then line order
        self.write("[ ] First | prio: 2 | added: 2026-10-05 | id: aa11\n[ ] Older | prio: 2 | added: 2026-10-04 | id: bb22\n"
                   "[ ] Same as older | prio: 2 | added: 2026-10-04 | id: cc33\n")
        out = self.ok("next", "--count", "3")
        self.assertEqual([l.split()[1] for l in out.splitlines() if l[:2] in ("1.", "2.", "3.")], ["bb22", "cc33", "aa11"])

    def test_nothing_fits_shows_shortest(self):
        self.write("[ ] Big | type: book | len: 300p | id: aa11\n[ ] Bigger | type: book | len: 900p | id: bb22\n")
        out = self.ok("next", "--time", "30m")
        self.assertIn("1. aa11", out)
        self.assertIn("nothing fits 30m; this is the shortest", out)

    def test_empty_and_filters(self):
        self.ok()
        self.assertIn("nothing to read; add something with `nextread add`", self.ok("next"))
        self.add("A paper", "--type", "paper", "--tags", "x")
        self.assertIn("nothing to read", self.ok("next", "--type", "book"))
        self.assertIn("A paper", self.ok("next", "--tag", "x"))

    def test_bad_flags(self):
        self.ok()
        self.assertIn("--count", self.err("next", "--count", "11"))
        self.assertIn("--count", self.err("next", "--count", "0"))
        self.assertIn("--time", self.err("next", "--time", "soon"))


class F7Check(CliCase):
    def test_check_and_fix(self):
        self.write("# my list\n[ ] Has id | added: 2026-10-01 | id: aa11\n[ ] No id here | prio: 2\n[?] malformed one | prio: 1\n"
                   "[ ] Messy order | id: bb22 | prio: 1 | added: 2026-09-01\n")
        rc, out, err = self.run_cli("check")
        self.assertEqual(rc, 1)
        self.assertIn("line 3: missing id", out)
        self.assertIn("line 3: missing added date", out)
        self.assertIn("line 4: unknown status marker", out)
        self.assertIn("[?] malformed one | prio: 1", out)
        before = self.read().splitlines()
        out = self.run_cli("check", "--fix")[1]
        after = self.read().splitlines()
        self.assertIn("fixed line 3: assigned id", out)
        self.assertIn("line 5: put fields in standard order", out)
        self.assertEqual(after[0], before[0])
        self.assertEqual(after[1], before[1])
        self.assertEqual(after[3], "[?] malformed one | prio: 1")
        self.assertRegex(after[2], r"^\[ \] No id here \| prio: 2 \| added: 2026-10-11 \| id: [0-9a-z]{4}$")
        self.assertEqual(after[4], "[ ] Messy order | prio: 1 | added: 2026-09-01 | id: bb22")
        self.assertIn("1 problem", out)

    def test_clean_file(self):
        self.add("Fine")
        self.assertIn("1 item, 0 problems", self.ok("check"))

    def test_duplicate_id_later_line_gets_new_id(self):
        self.write("[ ] One | added: 2026-10-01 | id: aa11\n[ ] Two | added: 2026-10-01 | id: aa11\n")
        rc, out, _ = self.run_cli("check")
        self.assertIn("line 2: duplicate id aa11", out)
        out = self.run_cli("check", "--fix")[1]
        self.assertIn("fixed line 2: duplicate id aa11 replaced with", out)
        lines = self.read().splitlines()
        self.assertTrue(lines[0].endswith("id: aa11"))
        self.assertFalse(lines[1].endswith("id: aa11"))
        self.assertIn("0 problems", out)

    def test_status_date_problems(self):
        self.write("[x] Done no date | added: 2026-10-01 | id: aa11\n[ ] Bad | prio: 9 | added: 2026-02-30 | id: bb22\n")
        out = self.run_cli("check")[1]
        self.assertIn("done item without a done date", out)
        self.assertIn("prio must be", out)
        self.assertIn("added must be a date", out)

    def test_other_commands_warn_and_preserve_bad_lines(self):
        self.write("# c\n[ ] Good | id: aa11 | added: 2026-10-01\nrubbish\n[?] more rubbish\n")
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("2 lines not understood; run `nextread check`", err)
        self.ok("start", "aa11")
        self.assertEqual(self.read().splitlines()[2:], ["rubbish", "[?] more rubbish"])

    def test_open_runs_editor_then_check(self):
        self.ok()
        script = os.path.join(self.tmp, "ed.sh")
        with open(script, "w") as fh:
            fh.write('#!/bin/sh\nprintf "[ ] Typed by hand\\n[bad\\n" >> "$1"\n')
        os.chmod(script, 0o755)
        rc, out, err = self.run_cli("open", env={"EDITOR": script})
        self.assertEqual(rc, 1)
        self.assertIn("missing id", out)
        self.assertIn("1 item, ", out)


class F8StatsExport(CliCase):
    def setUp(self):
        super().setUp()
        self.write(
            "# list\n"
            "[x] Book A | type: book | len: 100p | started: 2026-10-01 | done: 2026-10-05 | added: 2026-09-01 | rating: 5 | id: aa11\n"
            "[x] Paper B | type: paper | len: 30m | started: 2026-10-03 | done: 2026-10-07 | added: 2026-10-02 | id: bb22\n"
            "[x] Article C | type: article | done: 2026-09-20 | added: 2026-09-01 | id: cc33\n"
            "[x] No len | type: video | done: 2026-10-09 | added: 2026-10-01 | colour: red | id: dd44\n"
            "[-] Dropped | dropped: 2026-10-02 | added: 2026-08-01 | id: ee55\n"
            "[ ] Waiting old | added: 2026-01-01 | id: ff66\n"
            "[ ] Waiting newer | added: 2026-05-01 | id: gg77\n"
            "[ ] Waiting newest | added: 2026-10-10 | id: hh88\n"
            "[ ] Waiting mid | added: 2026-03-01 | id: ii99\n")

    def test_stats_month(self):
        out = self.ok("stats", "--month", "2026-10")
        self.assertIn("finished:    3", out)
        self.assertIn("added:       3", out)
        self.assertIn("book 1", out)
        self.assertIn("pages:       100", out)
        self.assertIn("minutes:     230", out)  # 100p*2 + 30m
        self.assertIn("1 finished item without len", out)
        self.assertIn("avg days start to done: 4.0", out)
        self.assertIn("dropped:     1", out)
        self.assertIn("backlog:     4 to-read", out)
        oldest = out.split("oldest waiting:")[1].strip().splitlines()
        self.assertEqual([l.split()[0] for l in oldest], ["ff66", "ii99", "gg77"])

    def test_stats_default_month_and_year(self):
        self.assertEqual(self.ok("stats"), self.ok("stats", "--month", "2026-10"))
        out = self.ok("stats", "--year", "2026")
        self.assertIn("finished:    4", out)

    def test_stats_bad_format(self):
        self.assertIn("YYYY-MM", self.err("stats", "--month", "2026-13"))
        self.assertIn("YYYY-MM", self.err("stats", "--month", "oct"))
        self.assertIn("YYYY", self.err("stats", "--year", "26"))

    def test_export_csv_with_header_and_extra(self):
        out_path = os.path.join(self.tmp, "f.csv")
        self.assertIn("exported 9 items to", self.ok("export", "--format", "csv", "--out", out_path))
        rows = list(csv.reader(io.StringIO(self.read(out_path))))
        self.assertEqual(rows[0], ["id", "status", "title", "by", "type", "tags", "prio", "len", "url", "note",
                                   "added", "started", "done", "dropped", "rating", "extra"])
        self.assertEqual(len(rows), 10)
        by_id = {r[0]: r for r in rows[1:]}
        self.assertEqual(by_id["dd44"][-1], "colour: red")
        self.assertEqual(by_id["aa11"][14], "5")

    def test_export_json_and_filters(self):
        rows = json.loads(self.ok("export", "--format", "json", "--status", "done"))
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["id"] for r in rows if r["extra"]], ["dd44"])
        rows = json.loads(self.ok("export", "--format", "json", "--from", "2026-10-01", "--to", "2026-10-31"))
        # done items by done date; the rest by added date
        self.assertEqual(sorted(r["id"] for r in rows), ["aa11", "bb22", "dd44", "hh88"])

    def test_export_markdown(self):
        out = self.ok("export", "--format", "md")
        self.assertIn("## To read (4)", out)
        self.assertIn("## Done (4)", out)
        self.assertIn("- [x] Book A", out)
        self.assertIn("- [ ] Waiting old", out)
        self.assertIn("colour: red", out)

    def test_export_errors(self):
        target = os.path.join(self.tmp, "o.json")
        self.ok("export", "--format", "json", "--out", target)
        self.assertIn("already exists", self.err("export", "--format", "json", "--out", target))
        self.ok("export", "--format", "json", "--out", target, "--force")
        self.assertIn("YYYY-MM-DD", self.err("export", "--format", "csv", "--from", "10/01/2026"))
        bad = os.path.join(self.tmp, "nodir", "x", "o.csv")
        os.makedirs(os.path.join(self.tmp, "nodir"))
        os.chmod(os.path.join(self.tmp, "nodir"), 0o500)
        try:
            if os.access(os.path.join(self.tmp, "nodir"), os.W_OK):
                self.skipTest("running as a user who can write anywhere")
            err = self.err("export", "--format", "csv", "--out", bad, code=3)
            self.assertIn("nodir", err)
        finally:
            os.chmod(os.path.join(self.tmp, "nodir"), 0o700)


if __name__ == "__main__":
    unittest.main()
