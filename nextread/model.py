"""The list file: lossless parsing, item fields, validation.

Every line is kept as read. Only items a command marks dirty are re-serialised;
comments, blank lines, unparseable lines and untouched items come back byte for byte.
"""
import re
from datetime import date

from .config import TYPES

FORMAT = 1
MARKERS = {" ": "to-read", ">": "reading", "x": "done", "-": "dropped"}
MARK_OF = dict((v, k) for k, v in MARKERS.items())
STATUSES = ["to-read", "reading", "done", "dropped"]
STATUS_RANK = dict((s, i) for i, s in enumerate(STATUSES))
KNOWN_KEYS = ["by", "type", "tags", "prio", "len", "url", "note", "added", "started", "done", "dropped", "rating", "id"]
KEY_RANK = dict((k, i) for i, k in enumerate(KNOWN_KEYS))
DATE_KEYS = ("added", "started", "done", "dropped")
ALLOWED_TRANSITIONS = {
    "to-read": ("reading", "done", "dropped"),
    "reading": ("done", "dropped", "to-read"),
    "done": (),
    "dropped": (),
}

HEADER = [
    "# Nextread reading list - format: %d" % FORMAT,
    "# One item per line; fields are separated by ' | ' and a literal | is written \\|.",
    "# Status: [ ] to-read  [>] reading  [x] done  [-] dropped. Keys: by type tags prio len url note added started done dropped rating id",
    "# Comments (like this) and blank lines are kept. You can edit this file by hand; `nextread check` validates it.",
    "# Example: [ ] Designing Data-Intensive Applications | by: Martin Kleppmann | type: book | tags: systems, db | prio: 1 | len: 600p | added: 2026-10-01 | id: k3f9",
]

_SEG_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:\s*(.*)$")
_LINE_RE = re.compile(r"^\[(.?)\](?:\s+(.*))?$")
_LEN_RE = re.compile(r"^(\d+)\s*([pm])$", re.I)
_URL_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://[^\s/]+\S*$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TAG_RE = re.compile(r"^[a-z0-9-]+$")
_ID_RE = re.compile(r"^[a-z0-9]{4}$")
_FORMAT_RE = re.compile(r"format:\s*(\d+)")


def esc(v):
    return v.replace("|", "\\|")


def unesc(v):
    return v.replace("\\|", "|")


class Item(object):
    __slots__ = ("status", "title", "pairs", "doc", "dirty")

    def __init__(self, status, title, pairs, doc=None, dirty=False):
        self.status = status
        self.title = title
        self.pairs = pairs  # list of [key, value]; known keys lowercase
        self.doc = doc
        self.dirty = dirty

    def get(self, key):
        key = key.lower()
        for k, v in self.pairs:
            if k.lower() == key:
                return v
        return None

    def set(self, key, value):
        for p in self.pairs:
            if p[0].lower() == key:
                p[1] = value
                self.dirty = True
                return
        rank = KEY_RANK[key] if key in KEY_RANK else 100
        pos = len(self.pairs)
        for i, (k, _) in enumerate(self.pairs):
            if KEY_RANK.get(k, 100) > rank:
                pos = i
                break
        self.pairs.insert(pos, [key, value])
        self.dirty = True

    def remove(self, key):
        before = len(self.pairs)
        self.pairs = [p for p in self.pairs if p[0].lower() != key.lower()]
        if len(self.pairs) != before:
            self.dirty = True

    def set_status(self, status):
        self.status = status
        self.dirty = True

    def set_title(self, title):
        self.title = title
        self.dirty = True

    def normalise_order(self):
        new = sorted(self.pairs, key=lambda p: KEY_RANK.get(p[0], 100))
        if [id(p) for p in new] != [id(p) for p in self.pairs]:
            self.pairs = new
            self.dirty = True
            return True
        return False

    def text(self):
        parts = ["[%s] %s" % (MARK_OF[self.status], esc(self.title))]
        for k, v in self.pairs:
            parts.append("%s: %s" % (k, esc(v)) if v else "%s:" % k)
        return " | ".join(parts)

    # typed views (tolerant of bad values; `validate_item` reports them)
    @property
    def id(self):
        return self.get("id") or ""

    @property
    def kind(self):
        t = (self.get("type") or "").lower()
        return t if t in TYPES else "article"

    @property
    def prio(self):
        v = self.get("prio")
        return int(v) if v in ("1", "2", "3") else 2

    @property
    def tags(self):
        return split_tags(self.get("tags") or "")

    @property
    def length(self):
        """(number, 'p'|'m') or None."""
        m = _LEN_RE.match(self.get("len") or "")
        if m and 1 <= int(m.group(1)) <= 5000:
            return int(m.group(1)), m.group(2).lower()
        return None

    def date(self, key):
        v = self.get(key)
        if v and _DATE_RE.match(v):
            try:
                return date(int(v[:4]), int(v[5:7]), int(v[8:]))
            except ValueError:
                return None
        return None

    def minutes(self, cfg):
        ln = self.length
        if ln:
            return ln[0] * cfg["len.page_minutes"] if ln[1] == "p" else ln[0]
        return cfg["len.default." + self.kind]

    def fields_dict(self):
        return dict((k, v) for k, v in self.pairs)


def split_tags(text):
    out = []
    for t in text.split(","):
        t = t.strip()
        if t and t not in out:
            out.append(t)
    return out


class Line(object):
    __slots__ = ("raw", "eol", "kind", "item", "reason")

    def __init__(self, raw, eol, kind, item=None, reason=None):
        self.raw = raw
        self.eol = eol
        self.kind = kind  # item | comment | blank | bad
        self.item = item
        self.reason = reason


def parse_line(text):
    """Returns (kind, item, reason)."""
    s = text.strip()
    if not s:
        return "blank", None, None
    if s.startswith("#"):
        return "comment", None, None
    m = _LINE_RE.match(s)
    if not m:
        return "bad", None, "no status marker (expected [ ], [>], [x] or [-])"
    mark = m.group(1).lower()
    if mark not in MARKERS:
        return "bad", None, 'unknown status marker "[%s]"' % m.group(1)
    rest = m.group(2) or ""
    segs = rest.split(" | ")
    title = unesc(segs[0]).strip()
    if not title:
        return "bad", None, "missing title"
    pairs = []
    for seg in segs[1:]:
        sm = _SEG_RE.match(seg.strip())
        if not sm:
            return "bad", None, 'field "%s" is not "key: value"' % seg.strip()[:40]
        key = sm.group(1)
        if key.lower() in KEY_RANK:
            key = key.lower()
        pairs.append([key, unesc(sm.group(2)).strip()])
    return "item", Item(MARKERS[mark], title, pairs), None


class Document(object):
    def __init__(self, path, data):
        self.path = path
        self.existed = data is not None
        self.lines = []
        self.bom = False
        self.eol = "\n"
        text = (data or b"").decode("utf-8", errors="surrogateescape")
        if text.startswith("﻿"):
            self.bom = True
            text = text[1:]
        crlf = lf = 0
        for piece in re.findall(r"[^\n]*\n|[^\n]+", text):
            if piece.endswith("\r\n"):
                raw, eol = piece[:-2], "\r\n"
                crlf += 1
            elif piece.endswith("\n"):
                raw, eol = piece[:-1], "\n"
                lf += 1
            else:
                raw, eol = piece, ""
            kind, item, reason = parse_line(raw)
            if item is not None:
                item.doc = self
            self.lines.append(Line(raw, eol, kind, item, reason))
        if crlf and crlf >= lf:
            self.eol = "\r\n"
        self.format = self._detect_format()

    def _detect_format(self):
        for ln in self.lines[:15]:
            if ln.kind == "comment":
                m = _FORMAT_RE.search(ln.raw)
                if m:
                    return int(m.group(1))
        return FORMAT

    @property
    def items(self):
        return [l.item for l in self.lines if l.item is not None]

    @property
    def bad_lines(self):
        return [l for l in self.lines if l.kind == "bad"]

    def looks_like_list(self):
        nonblank = [l for l in self.lines if l.kind != "blank"]
        bad = len([l for l in nonblank if l.kind == "bad"])
        return not nonblank or bad * 2 <= len(nonblank)

    def ensure_header(self):
        if not self.lines:
            for h in HEADER:
                self.lines.append(Line(h, None, "comment"))

    def _append_line(self, line):
        if self.lines and self.lines[-1].eol == "":
            self.lines[-1].eol = self.eol
        self.lines.append(line)

    def append_item(self, item):
        self.ensure_header()
        item.doc = self
        item.dirty = True
        self._append_line(Line(None, None, "item", item))

    def append_raw(self, text):
        kind, item, reason = parse_line(text)
        if item is not None:
            item.doc = self
        self._append_line(Line(text, None, kind, item, reason))

    def raw_of(self, item):
        for l in self.lines:
            if l.item is item:
                return item.text() if (l.raw is None or item.dirty) else l.raw
        return item.text()

    def remove_item(self, item):
        self.lines = [l for l in self.lines if l.item is not item]

    def lineno(self, item):
        for i, l in enumerate(self.lines, 1):
            if l.item is item:
                return i
        return None

    def upgrade_header(self):
        for ln in self.lines[:15]:
            if ln.kind == "comment":
                m = _FORMAT_RE.search(ln.raw)
                if m and int(m.group(1)) < FORMAT:
                    ln.raw = ln.raw[:m.start(1)] + str(FORMAT) + ln.raw[m.end(1):]
                    return

    def sort_items(self):
        """write.order = sort: non-item lines first (in order), then items by status/prio/added."""
        others = [l for l in self.lines if l.item is None]
        items = [l for l in self.lines if l.item is not None]
        far = date(9999, 12, 31)
        items.sort(key=lambda l: (STATUS_RANK[l.item.status], l.item.prio, l.item.date("added") or far))
        self.lines = others + items
        for l in self.lines[:-1]:
            if l.eol == "" or l.eol is None:
                l.eol = self.eol

    def render(self):
        out = ["﻿"] if self.bom else []
        for l in self.lines:
            if l.item is not None and (l.item.dirty or l.raw is None):
                out.append(l.item.text())
            else:
                out.append(l.raw)
            out.append(self.eol if l.eol is None else l.eol)
        return "".join(out).encode("utf-8", errors="surrogateescape")


# ---- validation ------------------------------------------------------------

def parse_len(text):
    m = _LEN_RE.match(text.strip())
    if not m or not 1 <= int(m.group(1)) <= 5000:
        return None
    return "%d%s" % (int(m.group(1)), m.group(2).lower())


def valid_date(text):
    if not _DATE_RE.match(text):
        return False
    try:
        date(int(text[:4]), int(text[5:7]), int(text[8:]))
    except ValueError:
        return False
    return True


def check_value(key, value, cfg):
    """Return an error message for a field value, or None. Messages name the allowed values."""
    if "\n" in value or "\r" in value:
        return "%s must be a single line" % key
    if value.endswith("\\"):
        return "%s must not end with a backslash" % key
    if key == "type":
        if value not in TYPES:
            return "type must be one of: %s (got %r)" % (", ".join(TYPES), value)
    elif key == "tags":
        tags = split_tags(value)
        for t in tags:
            if not _TAG_RE.match(t):
                return "tags must be lowercase letters, digits and hyphens, comma separated (got %r)" % t
        if len(tags) > cfg["limits.tags"]:
            return "tags: at most %d allowed (got %d)" % (cfg["limits.tags"], len(tags))
    elif key == "prio":
        if value not in ("1", "2", "3"):
            return "prio must be 1, 2 or 3 (got %r)" % value
    elif key == "len":
        if parse_len(value) is None:
            return "len must be a whole number of pages or minutes from 1 to 5000, like 300p or 25m (got %r)" % value
    elif key == "url":
        if not _URL_RE.match(value):
            return "url must look like https://example.com/page (got %r)" % value
    elif key == "note":
        if len(value) > cfg["limits.note"]:
            return "note must be at most %d characters (got %d)" % (cfg["limits.note"], len(value))
    elif key in DATE_KEYS:
        if not valid_date(value):
            return "%s must be a date like YYYY-MM-DD (got %r)" % (key, value)
    elif key == "rating":
        if value not in ("1", "2", "3", "4", "5"):
            return "rating must be 1 to 5 (got %r)" % value
    elif key == "id":
        if not _ID_RE.match(value):
            return "id must be 4 lowercase letters or digits (got %r)" % value
    return None


def check_title(title, cfg):
    if not title.strip():
        return "title must not be empty"
    if len(title) > cfg["limits.title"]:
        return "title must be 1 to %d characters (got %d)" % (cfg["limits.title"], len(title))
    if "\n" in title or "\r" in title:
        return "title must be a single line"
    if title.endswith("\\"):
        return "title must not end with a backslash"
    return None


def item_problems(item, cfg):
    """Reasons an existing item is invalid. Missing id/added are reported here too."""
    out = []
    err = check_title(item.title, cfg)
    if err:
        out.append(err)
    seen = set()
    for k, v in item.pairs:
        kl = k.lower()
        if kl in seen:
            out.append("duplicate key %s" % k)
        seen.add(kl)
        if kl in KEY_RANK and v:
            e = check_value(kl, v, cfg)
            if e:
                out.append(e)
        elif kl in KEY_RANK and not v and kl in ("id", "added", "type", "prio", "len", "rating"):
            out.append("%s is empty" % kl)
    if item.get("rating") and item.status != "done":
        out.append("rating is only allowed on done items")
    if item.status == "done" and not item.get("done"):
        out.append("done item without a done date")
    if item.status == "dropped" and not item.get("dropped"):
        out.append("dropped item without a dropped date")
    if item.status != "done" and item.get("done"):
        out.append("done date on an item that is not done")
    if item.status != "dropped" and item.get("dropped"):
        out.append("dropped date on an item that is not dropped")
    if not item.get("id"):
        out.append("missing id")
    if not item.get("added"):
        out.append("missing added date")
    return out


_PUNCT = re.compile(r"[\W_]+", re.U)


def norm_title(t):
    return _PUNCT.sub("", t.lower())


def norm_url(u):
    u = u.strip()
    return u[:-1] if u.endswith("/") else u
