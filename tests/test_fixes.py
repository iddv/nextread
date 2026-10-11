"""Regression tests for verifier findings and operator settings."""
import os
import unittest

from helpers import CliCase


class E5TagLimits(CliCase):
    def test_bad_tags_and_limits_refused_and_nothing_written(self):
        self.ok()
        before = self.read()
        for bad in ("Systems", "a_b", "two words"):
            self.assertIn("tags must be", self.err("add", "T", "--tags", bad))
        self.err("add", "T", "--tags", ",".join("t%d" % i for i in range(11)))
        self.err("add", "T", "--note", "n" * 501)
        self.assertEqual(self.read(), before)
        self.ok("add", "T10", "--tags", ",".join("t%d" % i for i in range(10)))
        self.ok("add", "T500", "--note", "n" * 500)


class X7BadLineWarning(CliCase):
    def test_write_commands_warn(self):
        self.write("# h\njunk1\njunk2\n[ ] One | id: aa11 | added: 2026-10-01\n")
        w = "2 lines not understood; run `nextread check`"
        for args in (["add", "Two"], ["edit", "one", "--prio", "1"], ["start", "one"], ["done", "one"]):
            rc, out, err = self.run_cli(*args)
            self.assertEqual(rc, 0, err)
            self.assertIn(w, err)
        self.assertIn("junk1\njunk2\n", self.read())


class E35NonUtf8(CliCase):
    def test_no_traceback_and_lossless(self):
        raw = b"# Nextread reading list - format: 1\n[ ] \xff\xfe bad | id: cc33 | added: 2026-10-01\n"
        os.makedirs(os.path.dirname(self.list), exist_ok=True)
        with open(self.list, "wb") as fh:
            fh.write(raw)
        for args in (["list"], ["next"], ["export", "--format", "json"], ["export", "--format", "csv"], ["show", "cc33"]):
            rc, out, err = self.run_cli(*args)
            self.assertEqual(rc, 0, (args, err))
            self.assertNotIn("Traceback", err)
        self.assertIn("\\udcff", self.ok("list"))
        out = self.ok("export", "--format", "md", "--out", os.path.join(self.tmp, "o.md"))
        with open(os.path.join(self.tmp, "o.md"), "rb") as fh:
            self.assertIn(b"\xff\xfe", fh.read())
        self.ok("start", "cc33")
        with open(self.list, "rb") as fh:
            self.assertIn(b"\xff\xfe bad", fh.read())


class S1ReopenClearRating(CliCase):
    def reopened_line(self, **kw):
        i = self.add("Rated")
        self.ok("done", i, "--rating", "4")
        self.ok("reopen", i, **kw)
        return self.read().splitlines()[-1]

    def test_default_clears_rating(self):
        self.assertNotIn("rating", self.reopened_line())

    def test_false_keeps_rating(self):
        self.ok("config", "set", "reopen.clear_rating", "false")
        line = self.reopened_line()
        self.assertIn("rating: 4", line)
        self.assertNotIn("done:", line)

    def test_env_overrides_config(self):
        self.ok("config", "set", "reopen.clear_rating", "true")
        self.assertIn("rating: 4", self.reopened_line(env={"REOPEN_CLEAR_RATING": "false"}))
        self.assertIn("env REOPEN_CLEAR_RATING", self.ok("config", env={"REOPEN_CLEAR_RATING": "false"}))


class S2ReopenKeepStarted(CliCase):
    def reopened_line(self, source, **kw):
        i = self.add("Started")
        self.ok("start", i)
        if source == "done":
            self.ok("done", i)
        elif source == "dropped":
            self.ok("drop", i)
        self.ok("reopen", i, **kw)
        return self.read().splitlines()[-1]

    def test_default_keeps_started(self):
        for source in ("done", "dropped", "reading"):
            self.assertIn("started: 2026-10-11", self.reopened_line(source))
            self.ok("rm", "--yes", "started")

    def test_false_removes_started(self):
        self.ok("config", "set", "reopen.keep_started", "false")
        for source in ("done", "dropped", "reading"):
            line = self.reopened_line(source)
            self.assertTrue(line.startswith("[ ]"))
            self.assertNotIn("started", line)
            self.ok("rm", "--yes", "started")

    def test_env_overrides_config(self):
        self.assertNotIn("started:", self.reopened_line("done", env={"REOPEN_KEEP_STARTED": "false"}))


class S3VarietyWithoutHistory(CliCase):
    def setUp(self):
        super().setUp()
        self.write("[ ] A | prio: 2 | added: 2026-10-10 | id: aa11\n")

    def test_default_none(self):
        out = self.ok("next", "--why")
        self.assertIn("variety 0", out)

    def test_all_gives_everyone_the_bonus(self):
        self.ok("config", "set", "next.variety_without_history", "all")
        out = self.ok("next", "--why")
        self.assertIn("variety 10", out)
        self.assertIn("fresh start", out)

    def test_env_override_and_history_still_wins(self):
        self.assertIn("variety 10", self.ok("next", "--why", env={"NEXT_VARIETY_WITHOUT_HISTORY": "all"}))
        self.write("[x] Last | type: article | done: 2026-10-01 | id: dd44\n[ ] A | type: article | added: 2026-10-10 | id: aa11\n")
        self.assertIn("variety 0", self.ok("next", "--why", env={"NEXT_VARIETY_WITHOUT_HISTORY": "all"}))


class S4DuplicatesCheckArchive(CliCase):
    def setUp(self):
        super().setUp()
        self.ok("config", "set", "file.done_items", "archive")
        self.ok("done", self.add("Archived book"))

    def test_default_true_rejects_duplicate_of_archived_item(self):
        self.assertIn("duplicate of", self.err("add", "Archived book"))

    def test_false_only_checks_list_file(self):
        self.ok("config", "set", "add.duplicates_check_archive", "false")
        self.ok("add", "Archived book")
        self.assertIn("duplicate of", self.err("add", "Archived book"))  # now in the list file

    def test_env_override(self):
        self.ok("add", "Archived book", env={"ADD_DUPLICATES_CHECK_ARCHIVE": "false"})
        self.assertIn("env ADD_DUPLICATES_CHECK_ARCHIVE", self.ok("config", env={"ADD_DUPLICATES_CHECK_ARCHIVE": "false"}))


if __name__ == "__main__":
    unittest.main()
