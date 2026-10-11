"""Settings, archive, locking, conflicts, line endings, permissions, speed."""
import json
import os
import stat
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from helpers import CliCase  # noqa: E402
from nextread import store  # noqa: E402
from nextread.config import Config  # noqa: E402
from nextread.errors import BusyError, ConflictError  # noqa: E402


class Archive(CliCase):
    def setUp(self):
        super().setUp()
        self.archive = os.path.join(self.tmp, "data", "reading.archive.txt")
        self.ok("config", "set", "file.done_items", "archive")

    def test_done_and_dropped_move_to_archive_and_are_counted_once(self):
        a = self.add("Finish me")
        b = self.add("Drop me")
        c = self.add("Stay")
        self.ok("done", a, "--rating", "5")
        self.ok("drop", b)
        main = self.read()
        self.assertNotIn("Finish me", main)
        self.assertIn("Stay", main)
        arch = self.read(self.archive)
        self.assertIn("[x] Finish me", arch)
        self.assertIn("[-] Drop me", arch)
        self.assertEqual(stat.S_IMODE(os.stat(self.archive).st_mode), 0o600)
        rows = json.loads(self.ok("export", "--format", "json"))
        self.assertEqual(sorted(r["title"] for r in rows), ["Drop me", "Finish me", "Stay"])
        self.assertIn("Finish me", self.ok("list", "--status", "done"))
        self.assertIn("finished:    1", self.ok("stats"))
        self.assertIn("1 item", self.ok("list").strip().splitlines()[-1])

    def test_reopen_moves_back_and_undo_restores_both_files(self):
        a = self.add("Finish me")
        main_before = self.read()
        self.ok("done", a)
        self.ok("undo")
        self.assertEqual(self.read(), main_before)
        self.assertFalse(os.path.exists(self.archive))
        self.ok("done", a)
        self.ok("reopen", a)
        self.assertIn("[ ] Finish me", self.read())
        self.assertNotIn("Finish me", self.read(self.archive).split("# Example")[1])

    def test_edit_archived_item_in_place(self):
        a = self.add("Finish me")
        self.ok("done", a)
        self.ok("edit", a, "--tags", "x")
        self.assertIn("tags: x", self.read(self.archive))
        self.assertNotIn("Finish me", self.read())

    def test_id_in_both_files_counted_once_and_reported(self):
        a = self.add("Finish me")
        self.ok("done", a)
        line = [l for l in self.read(self.archive).splitlines() if "Finish me" in l][0]
        with open(self.list, "a") as fh:
            fh.write(line + "\n")
        rows = json.loads(self.ok("export", "--format", "json"))
        self.assertEqual(len(rows), 1)
        rc, out, err = self.run_cli("check")
        self.assertIn("duplicate id", out)


class WriteOrder(CliCase):
    def test_sort_orders_items_keeping_comments_on_top(self):
        self.write("# top\n[x] Done | prio: 1 | added: 2026-01-01 | done: 2026-02-01 | id: aa11\n[ ] Low | prio: 3 | added: 2026-01-01 | id: bb22\n"
                   "# a note in the middle\n[ ] High | prio: 1 | added: 2026-03-01 | id: cc33\n[>] Now | prio: 2 | added: 2026-01-01 | id: dd44\n")
        self.ok("config", "set", "write.order", "sort")
        self.add("Newest", "--prio", "1")
        lines = self.read().splitlines()
        self.assertEqual(lines[:2], ["# top", "# a note in the middle"])
        titles = [l.split(" | ")[0][4:] for l in lines[2:]]
        self.assertEqual(titles, ["High", "Newest", "Low", "Now", "Done"])

    def test_preserve_keeps_order(self):
        self.write("[ ] B | added: 2026-01-01 | id: aa11\n[ ] A | prio: 1 | added: 2026-01-01 | id: bb22\n")
        self.add("C")
        self.assertEqual([l[4:5] for l in self.read().splitlines()], ["B", "A", "C"])


class Config_(CliCase):
    def test_config_shows_sources_and_set_validates(self):
        out = self.ok("config")
        self.assertIn("(env NEXTREAD_FILE)", out)
        self.assertIn("add.duplicates", out)
        self.ok("config", "set", "next.weight.prio1", "50")
        self.assertRegex(self.ok("config"), r"next.weight.prio1\s+= 50\s+\(config\)")
        self.assertIn("one of: reject, warn", self.err("config", "set", "add.duplicates", "maybe"))
        self.assertIn("unknown setting", self.err("config", "set", "nope", "1"))
        self.assertIn("between", self.err("config", "set", "history.size", "0"))
        self.assertIn("add.duplicates = reject", self.read(self.config))  # untouched lines stay commented defaults

    def test_file_precedence_flag_env_config(self):
        cfgfile = os.path.join(self.tmp, "from-config.txt")
        flagfile = os.path.join(self.tmp, "from-flag.txt")
        os.makedirs(os.path.dirname(self.config), exist_ok=True)
        with open(self.config, "w") as fh:
            fh.write("file = %s\n" % cfgfile)
        self.assertIn(self.list, self.ok("path"))  # env beats config
        env = dict(self.env)
        del env["NEXTREAD_FILE"]
        self.env = env
        self.assertIn(cfgfile, self.ok("path"))
        self.assertIn(flagfile, self.ok("path", "--file", flagfile))
        self.assertIn("--file", self.ok("config", "--file", flagfile))

    def test_bad_config_value_is_one_line_error(self):
        os.makedirs(os.path.dirname(self.config), exist_ok=True)
        with open(self.config, "w") as fh:
            fh.write("# c\nadd.duplicates = maybe\n")
        err = self.err("list")
        self.assertIn("line 2", err)
        self.assertEqual(err.count("\n"), 1)

    def test_path_lists_locations(self):
        out = self.ok("path")
        for word in ("list:", "archive:", "history:", "config:"):
            self.assertIn(word, out)

    def test_limits_follow_config(self):
        self.ok("config", "set", "limits.title", "5")
        self.assertIn("5 characters", self.err("add", "toolong"))


class Concurrency(CliCase):
    def cfg(self):
        os.environ["NEXTREAD_FILE"] = self.list
        os.environ["NEXTREAD_CONFIG"] = self.config
        self.addCleanup(os.environ.pop, "NEXTREAD_FILE", None)
        self.addCleanup(os.environ.pop, "NEXTREAD_CONFIG", None)
        return Config.load()

    def test_busy_lock_fails_after_timeout_with_exit_2(self):
        self.ok()
        self.ok("config", "set", "lock.timeout", "0.3")
        with open(self.list + ".lock", "w") as fh:
            fh.write(str(os.getpid()))  # a live process holds it
        start = time.time()
        err = self.err("add", "Blocked", code=2)
        self.assertIn("list is busy", err)
        self.assertLess(time.time() - start, 5)
        self.assertNotIn("Blocked", self.read())
        os.unlink(self.list + ".lock")
        self.add("Now fine")

    def test_stale_lock_from_dead_process_is_cleared(self):
        self.ok()
        with open(self.list + ".lock", "w") as fh:
            fh.write("999999999")
        if os.name == "posix":
            self.add("After stale lock")

    def test_lock_released_after_use_and_after_failure(self):
        self.add("A")
        self.assertFalse(os.path.exists(self.list + ".lock"))
        self.err("add", "B", "--prio", "9")
        self.assertFalse(os.path.exists(self.list + ".lock"))

    def test_file_changed_while_working_aborts_write(self):
        cfg = self.cfg()
        self.ok()
        with self.assertRaises(ConflictError) as cm:
            with store.transaction(cfg, "add x") as tx:
                from nextread.model import Item
                tx.lib.add_item(Item("to-read", "Mine", [["id", "zz99"]]))
                with open(self.list, "a") as fh:  # an editor saves meanwhile
                    fh.write("# edited elsewhere\n")
        self.assertIn("file changed while working; nothing written, run again", str(cm.exception))
        self.assertNotIn("Mine", self.read())
        self.assertIn("edited elsewhere", self.read())
        self.assertFalse(os.path.exists(self.list + ".lock"))
        self.assertEqual(store.history_entries(cfg), [])

    def test_second_transaction_waits_then_busy(self):
        cfg = self.cfg()
        cfg.values["lock.timeout"] = 0.2
        self.ok()
        with store.transaction(cfg, "outer"):
            with self.assertRaises(BusyError):
                with store.transaction(cfg, "inner"):
                    pass

    def test_no_temp_files_left_behind(self):
        self.add("A")
        self.add("B")
        names = os.listdir(os.path.dirname(self.list))
        self.assertFalse([n for n in names if n.endswith(".tmp")], names)


class FileProperties(CliCase):
    def test_crlf_preserved(self):
        self.write("# c\r\n[ ] Alpha | id: aa11 | added: 2026-10-01\r\n\r\n[ ] Beta | id: bb22 | added: 2026-10-01\r\n", newline="")
        self.ok("start", "alpha")
        self.add("Gamma")
        with open(self.list, "rb") as fh:
            data = fh.read()
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"))
        self.assertEqual(data.count(b"\r\n"), 5)

    def test_permissions_preserved_and_new_files_private(self):
        self.add("A")
        self.assertEqual(stat.S_IMODE(os.stat(self.list).st_mode), 0o600)
        os.chmod(self.list, 0o640)
        self.add("B")
        self.assertEqual(stat.S_IMODE(os.stat(self.list).st_mode), 0o640)
        hist = self.list + ".history"
        for n in os.listdir(hist):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(hist, n)).st_mode), 0o600)

    def test_missing_trailing_newline_and_blank_lines_untouched(self):
        self.write("# c\n\n\n[ ] Alpha | id: aa11 | added: 2026-10-01\n\n[ ] Last | id: bb22 | added: 2026-10-01")
        self.ok("edit", "alpha", "--prio", "1")
        self.assertEqual(self.read(), "# c\n\n\n[ ] Alpha | prio: 1 | id: aa11 | added: 2026-10-01\n\n[ ] Last | id: bb22 | added: 2026-10-01")

    def test_newer_format_is_read_only(self):
        text = "# Nextread reading list - format: 2\n[ ] Future | id: aa11 | added: 2026-10-01\n"
        self.write(text)
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertIn("Future", out)
        self.assertIn("newer format", err)
        self.assertIn("read-only", self.err("add", "x"))
        self.assertEqual(self.read(), text)

    def test_old_format_header_upgraded_on_write(self):
        self.write("# Nextread reading list - format: 0\n[ ] Old | id: aa11 | added: 2026-10-01\n")
        self.add("New")
        self.assertTrue(self.read().startswith("# Nextread reading list - format: 1\n"))

    def test_no_network_modules_imported(self):
        import subprocess
        code = "import sys, nextread.cli; bad=[m for m in ('socket','urllib.request','http.client','ssl') if m in sys.modules]; print(bad)"
        out = subprocess.run([sys.executable, "-c", code], env=self.env, capture_output=True, text=True).stdout
        self.assertEqual(out.strip(), "[]")


class Speed(CliCase):
    def test_five_thousand_items_load_list_and_rank_quickly(self):
        lines = ["# big"]
        for n in range(5000):
            lines.append("[ ] Item number %d | by: Author %d | type: %s | tags: t%d, common | prio: %d | len: %dp | added: 2026-%02d-%02d | id: %s"
                         % (n, n % 50, ["book", "paper", "article"][n % 3], n % 20, n % 3 + 1, n % 400 + 1, n % 9 + 1, n % 28 + 1,
                            ("%x" % (0x10000 + n))[-4:]))
        self.write("\n".join(lines) + "\n")
        from nextread import rank
        from nextread.cli import find_duplicate
        from datetime import date
        cfg = Config.load(self.list)
        t = time.time()
        lib = store.Library.load(cfg)
        items = lib.items
        picks, _ = rank.rank(lib, cfg, date(2026, 10, 11), time_limit=30, count=3)
        find_duplicate(items, "zzz", None)
        elapsed = time.time() - t
        self.assertEqual(len(items), 5000)
        self.assertEqual(len(picks), 3)
        self.assertLess(elapsed, 1.0)
        t = time.time()
        self.ok("list", "--tag", "common")
        self.assertLess(time.time() - t, 3.0)  # includes interpreter start-up


if __name__ == "__main__":
    unittest.main()
