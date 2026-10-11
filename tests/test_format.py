"""Parse / write round-trips and field validation (in-process)."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nextread.config import Config  # noqa: E402
from nextread.model import Document, item_problems, norm_title, parse_line  # noqa: E402

MESSY = (
    "# my list\n"
    "\n"
    "[ ] Dune | by: Frank Herbert | type: book | mood: epic | id: aa11\n"
    "   \n"
    "[?] broken line | prio: 1\n"
    "[x] Odd   spacing | BY: x |  prio:  1 | id: bb22 | done: 2026-01-01\n"
    "just some words\n"
    "[>] Pipes \\| in title | note: a \\| b | id: cc33"
)


class RoundTrip(unittest.TestCase):
    def test_untouched_file_is_byte_identical(self):
        for data in (MESSY, MESSY + "\n", MESSY.replace("\n", "\r\n"), "", "\n\n", "﻿# bom\n[ ] A | id: zz99\n"):
            raw = data.encode("utf-8")
            self.assertEqual(Document("x", raw).render(), raw)

    def test_invalid_utf8_survives(self):
        raw = b"# caf\xe9\n[ ] Title \xff | id: aa11\n"
        self.assertEqual(Document("x", raw).render(), raw)

    def test_classification(self):
        doc = Document("x", MESSY.encode())
        kinds = [l.kind for l in doc.lines]
        self.assertEqual(kinds, ["comment", "blank", "item", "blank", "bad", "item", "bad", "item"])
        self.assertEqual(len(doc.items), 3)
        self.assertIn("unknown status marker", doc.lines[4].reason)

    def test_unknown_fields_and_case_insensitive_keys(self):
        doc = Document("x", MESSY.encode())
        dune, odd, pipes = doc.items
        self.assertEqual(dune.get("mood"), "epic")
        self.assertEqual(odd.get("by"), "x")
        self.assertEqual(odd.get("prio"), "1")
        self.assertEqual(pipes.title, "Pipes | in title")
        self.assertEqual(pipes.get("note"), "a | b")

    def test_editing_one_item_changes_only_its_line(self):
        raw = MESSY.replace("\n", "\r\n").encode()
        doc = Document("x", raw)
        doc.items[0].set("prio", "1")
        out = doc.render().decode().split("\r\n")
        orig = raw.decode().split("\r\n")
        diff = [i for i in range(len(orig)) if orig[i] != out[i]]
        self.assertEqual(diff, [2])
        self.assertTrue(out[2].endswith("| id: aa11"))
        self.assertIn("mood: epic", out[2])

    def test_escape_roundtrip_on_rewrite(self):
        doc = Document("x", MESSY.encode())
        it = doc.items[2]
        it.dirty = True
        self.assertIn("[>] Pipes \\| in title | note: a \\| b | id: cc33", doc.render().decode())

    def test_append_after_missing_final_newline(self):
        doc = Document("x", b"[ ] A | id: aa11")
        from nextread.model import Item
        doc.append_item(Item("to-read", "B", [["id", "bb22"]]))
        self.assertEqual(doc.render(), b"[ ] A | id: aa11\n[ ] B | id: bb22\n")

    def test_new_lines_use_crlf_in_crlf_file(self):
        doc = Document("x", b"[ ] A | id: aa11\r\n")
        from nextread.model import Item
        doc.append_item(Item("to-read", "B", [["id", "bb22"]]))
        self.assertEqual(doc.render(), b"[ ] A | id: aa11\r\n[ ] B | id: bb22\r\n")

    def test_not_a_list(self):
        doc = Document("x", b"hello\nworld\nthis is prose\n[ ] one item\n")
        self.assertFalse(doc.looks_like_list())
        self.assertTrue(Document("x", MESSY.encode()).looks_like_list())

    def test_problems(self):
        cfg = Config.load()
        kind, it, _ = parse_line("[ ] T | prio: 9 | len: 12x | added: 2026-13-01 | rating: 4 | url: nope | tags: Bad Tag")
        probs = " ".join(item_problems(it, cfg))
        for needle in ("prio must be", "len must be", "added must be", "rating is only", "url must", "tags must", "missing id"):
            self.assertIn(needle, probs)

    def test_norm_title(self):
        self.assertEqual(norm_title("Hello,  World!"), norm_title("hello world"))


if __name__ == "__main__":
    unittest.main()
