"""Command-line interface: argument parsing and the commands."""
import argparse
import os
import re
import shlex
import subprocess
import sys
from datetime import date, datetime

from . import __version__
from . import config as cfgmod
from . import demo as demomod
from . import rank as rankmod
from . import reports
from .errors import IOFailure, NextreadError, UsageError, io_failure
from .model import (ALLOWED_TRANSITIONS, KNOWN_KEYS, MARK_OF, STATUSES, Item, check_title, check_value,
                    item_problems, norm_title, norm_url, parse_len, split_tags)
from .store import Library, Lock, make_dirs, read_bytes, transaction, undo as store_undo, write_atomic

STATUS_CHOICES = STATUSES + ["all"]
CLEARABLE = ["by", "type", "tags", "prio", "len", "url", "note", "rating"]
URL_ONLY = re.compile(r"^https?://\S+$")


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


class Ctx(object):
    def __init__(self, cfg, argv):
        self.cfg = cfg
        self.command = " ".join(argv)
        self.today = today()


def today():
    env = os.environ.get("NEXTREAD_TODAY")
    if env:
        try:
            return date.fromisoformat(env)
        except ValueError:
            raise UsageError("NEXTREAD_TODAY must look like YYYY-MM-DD (got %r)" % env)
    return date.today()


def warn(msg):
    print(msg, file=sys.stderr)


def plural(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def load(ctx, strict=True, warn_bad=True):
    lib = Library.load(ctx.cfg, strict=strict)
    if lib.readonly:
        warn("warning: list uses a newer format than this version understands; it is read-only")
    if warn_bad and lib.bad_count:
        warn("%s not understood; run `nextread check`" % plural(lib.bad_count, "line"))
    return lib


def txn(ctx):
    def on_load(lib):
        if lib.bad_count:
            warn("%s not understood; run `nextread check`" % plural(lib.bad_count, "line"))
    return transaction(ctx.cfg, ctx.command, on_load)


def label(item):
    return item.id or "----"


def ident(item):
    return item.id or '"%s"' % item.title


def resolve(items, ref):
    r = ref.strip()
    low = r.lower()
    hits = [i for i in items if i.id and i.id == low]
    if not hits:
        hits = [i for i in items if i.title.lower() == low]
    if not hits:
        hits = [i for i in items if low and low in i.title.lower()]
    if not hits:
        raise UsageError("no item %s" % ref)
    if len(hits) > 1:
        lines = ["%s matches %d items; use an id:" % (ref, len(hits))]
        lines += ["  %s  %s  (%s)" % (label(i), i.title, i.status) for i in hits]
        raise UsageError("\n".join(lines))
    return hits[0]


def find_duplicate(items, title, url, exclude=None):
    nt = norm_title(title)
    nu = norm_url(url) if url else None
    for i in items:
        if i is exclude:
            continue
        u = i.get("url")
        if nu and u and norm_url(u) == nu:
            return i
        if nt and norm_title(i.title) == nt:
            return i
    return None


def dup_message(d):
    return "duplicate of %s (%s): %s" % (label(d), d.status, d.title)


# ---- field flags -----------------------------------------------------------

def add_field_flags(p, edit=False):
    p.add_argument("--by", help="author or creator")
    p.add_argument("--type", help="book, paper, article, video or other")
    p.add_argument("--tags", help="comma-separated tags: lowercase letters, digits, hyphens")
    p.add_argument("--prio", help="1 (high), 2 or 3")
    p.add_argument("--len", help="length: 300p (pages) or 25m (minutes), 1 to 5000")
    p.add_argument("--url", help="link to the item")
    p.add_argument("--note", help="short note")
    if edit:
        p.add_argument("--title", help="new title")
        p.add_argument("--rating", help="rating 1-5 (done items only)")
        p.add_argument("--clear", action="append", default=[], metavar="FIELD",
                       help="remove an optional field (%s); repeatable" % ", ".join(CLEARABLE))


def collect_fields(args, cfg):
    fields = {}
    for key in ("by", "type", "tags", "prio", "len", "url", "note", "rating"):
        v = getattr(args, key, None)
        if v is None:
            continue
        v = v.strip()
        if key == "type":
            v = v.lower()
        elif key == "tags":
            v = ", ".join(split_tags(v))
        elif key == "len":
            v = parse_len(v) or v
        err = check_value(key, v, cfg) if v else "%s must not be empty (use --clear %s to remove it)" % (key, key)
        if key == "by" and v:
            err = check_value("by", v, cfg)
        if err:
            raise UsageError(err)
        fields[key] = v
    return fields


def set_fields(item, fields):
    for k, v in fields.items():
        if k == "tags" and not v:
            item.remove("tags")
        else:
            item.set(k, v)


# ---- commands --------------------------------------------------------------

def ensure_files(ctx):
    """Create the list (header only) and config if missing. Returns what was created."""
    cfg = ctx.cfg
    created = []
    if cfgmod.ensure_config_file(cfg):
        created.append("config")
    lock = Lock(cfg.lock_path, cfg["lock.timeout"])
    lock.acquire()
    try:
        data = read_bytes(cfg.list_path)
        if data is None:
            from .model import Document
            doc = Document(cfg.list_path, None)
            doc.ensure_header()
            write_atomic(cfg.list_path, doc.render())
            created.append("list")
    finally:
        lock.release()
    return created


def cmd_init(ctx, args):
    cfg = ctx.cfg
    if os.path.exists(cfg.list_path):
        Library.load(cfg, strict=True)  # refuses a file that is not a Nextread list
    ensure_files(ctx)
    lib = Library.load(cfg)
    print("list:   %s" % cfg.list_path)
    print("config: %s" % cfg.config_path)
    print(plural(len(lib.items), "item"))
    print("")
    print('  nextread add "Title"   add something to read')
    print("  nextread demo          load a demo list of about 40 items")
    print("  nextread help          show all commands")


def cmd_help(ctx, args):
    parser = build_parser()
    if args.topic:
        parser.parse_args([args.topic, "--help"])
    parser.print_help()


def cmd_path(ctx, args):
    cfg = ctx.cfg
    print("list:    %s" % cfg.list_path)
    print("archive: %s" % cfg.archive_path)
    print("history: %s" % cfg.history_dir)
    print("config:  %s" % cfg.config_path)
    print("lock:    %s" % cfg.lock_path)


def cmd_config(ctx, args):
    cfg = ctx.cfg
    rest = args.rest
    if rest:
        if rest[0] != "set" or len(rest) != 3:
            raise UsageError("usage: nextread config [set <key> <value>]")
        value = cfgmod.set_config_value(cfg, rest[1], rest[2])
        print("%s = %s  (saved to %s)" % (rest[1], value, cfg.config_path))
        return
    for w in cfg.warnings:
        warn("warning: " + w)
    print("config file: %s  (%s)" % (cfg.config_path, cfg.config_source))
    width = max(len(s.key) for s in cfgmod.SETTINGS)
    for s in cfgmod.SETTINGS:
        print("%-*s = %-12s (%s)" % (width, s.key, cfg[s.key], cfg.sources[s.key]))


def cmd_demo(ctx, args):
    cfg = ctx.cfg
    with txn(ctx) as tx:
        lib = tx.lib
        n = len(lib.items)
        if n:
            raise UsageError("list not empty; use `--file <new path>`")
        lib.main.ensure_header()
        for text in demomod.demo_lines(ctx.today):
            lib.main.append_raw(text)
        count = len(lib.main.items)
    print("loaded %d demo items into %s" % (count, cfg.list_path))
    print("try: nextread list | nextread next --time 30m | nextread check | nextread stats")


def cmd_add(ctx, args):
    cfg = ctx.cfg
    title = " ".join(args.title).strip()
    fields = collect_fields(args, cfg)
    if URL_ONLY.match(title) and "url" not in fields:
        fields["url"] = title
        fields.setdefault("type", "article")
    err = check_title(title, cfg)
    if err:
        raise UsageError(err)
    with txn(ctx) as tx:
        lib = tx.lib
        pool = lib.items if cfg["add.duplicates_check_archive"] == "true" else lib.main.items
        dup = find_duplicate(pool, title, fields.get("url"))
        if dup is not None:
            if cfg["add.duplicates"] == "reject":
                raise UsageError(dup_message(dup))
            warn("warning: " + dup_message(dup))
        item = Item("to-read", title, [])
        set_fields(item, fields)
        item.set("added", ctx.today.isoformat())
        item.set("id", lib.new_id())
        lib.add_item(item)
        text, new_id = item.text(), item.id
    print(text)
    print("added %s" % new_id)


def cmd_edit(ctx, args):
    cfg = ctx.cfg
    fields = collect_fields(args, cfg)
    clear = []
    for c in args.clear:
        c = c.lower()
        if c in clear:
            continue
        clear.append(c)
    new_title = None
    if args.title is not None:
        new_title = args.title.strip()
        err = check_title(new_title, cfg)
        if err:
            raise UsageError(err)
    if not fields and not clear and new_title is None:
        raise UsageError("nothing to change; give a flag such as --prio 1 (see `nextread edit --help`)")
    with txn(ctx) as tx:
        lib = tx.lib
        item = resolve(lib.items, args.ref)
        for c in clear:
            if c in fields or (c == "title"):
                raise UsageError("--clear %s conflicts with setting it in the same command" % c)
            if c not in CLEARABLE and not any(k == c for k, _ in item.pairs if k not in KNOWN_KEYS):
                raise UsageError("--clear: cannot clear %r; allowed: %s" % (c, ", ".join(CLEARABLE)))
        if "rating" in fields and item.status != "done":
            raise UsageError("rating is only allowed on done items")
        was_dirty = item.dirty
        before_text = item.doc.raw_of(item)
        before_state = (item.title, [tuple(p) for p in item.pairs])
        set_fields(item, fields)
        if new_title is not None:
            item.set_title(new_title)
        for c in clear:
            item.remove(c)
        if (item.title, [tuple(p) for p in item.pairs]) == before_state:
            item.dirty = was_dirty
            print("no change: %s" % before_text)
            return
        if new_title is not None or "url" in fields:
            dup = find_duplicate(lib.items, item.title, item.get("url"), exclude=item)
            if dup is not None:
                if cfg["add.duplicates"] == "reject":
                    raise UsageError(dup_message(dup))
                warn("warning: " + dup_message(dup))
        after_text = item.text()
    print("before: %s" % before_text)
    print("after:  %s" % after_text)


def transition(ctx, ref, target, verb, rating=None, note=None):
    cfg = ctx.cfg
    if rating is not None:
        err = check_value("rating", rating.strip(), cfg)
        if err:
            raise UsageError(err)
        rating = rating.strip()
    if note is not None:
        note = note.strip()
        err = check_value("note", note, cfg)
        if err:
            raise UsageError(err)
    iso = ctx.today.isoformat()
    with txn(ctx) as tx:
        lib = tx.lib
        item = resolve(lib.items, ref)
        cur = item.status
        if target not in ALLOWED_TRANSITIONS[cur]:
            hint = " (use `nextread reopen %s` first)" % (item.id or "<ref>") if cur in ("done", "dropped") else ""
            if cur == target:
                raise UsageError("%s is already %s%s" % (ident(item), cur, hint))
            raise UsageError("%s is %s; cannot %s%s" % (ident(item), cur, verb, hint))
        started = item.date("started")
        if target == "reading":
            item.set("started", iso)
        elif target == "done":
            item.set("done", iso)
            if rating:
                item.set("rating", rating)
        elif target == "dropped":
            item.set("dropped", iso)
        item.set_status(target)
        if note:
            item.set("note", note)
        if cfg["file.done_items"] == "archive" and target in ("done", "dropped"):
            lib.to_archive(item)
        info = ["%s is now %s: %s" % (label(item), target, item.title)]
        if target == "done":
            if started is not None:
                info.append("took %s" % plural((ctx.today - started).days, "day"))
            first = ctx.today.replace(day=1)
            n = len([i for i in lib.items if i.status == "done" and i.date("done") and i.date("done") >= first
                     and i.date("done").year == first.year and i.date("done").month == first.month])
            info.append("finished this month: %d" % n)
    print("\n".join(info))


def cmd_start(ctx, args):
    transition(ctx, args.ref, "reading", "start")


def cmd_done(ctx, args):
    transition(ctx, args.ref, "done", "finish", rating=args.rating, note=args.note)


def cmd_drop(ctx, args):
    transition(ctx, args.ref, "dropped", "drop", note=args.note)


def cmd_reopen(ctx, args):
    cfg = ctx.cfg
    with txn(ctx) as tx:
        lib = tx.lib
        item = resolve(lib.items, args.ref)
        if item.status == "to-read":
            raise UsageError("%s is already to-read" % ident(item))
        for k in ("done", "dropped"):
            item.remove(k)
        if ctx.cfg["reopen.clear_rating"] == "true":
            item.remove("rating")
        if ctx.cfg["reopen.keep_started"] == "false":
            item.remove("started")
        item.set_status("to-read")
        lib.to_main(item)
        msg = "%s is now to-read: %s" % (label(item), item.title)
    print(msg)


def cmd_rm(ctx, args):
    cfg = ctx.cfg
    lib = load(ctx, warn_bad=False)
    item = resolve(lib.items, args.ref)
    if not args.yes:
        sys.stdout.write('remove %s "%s"? [y/N] ' % (label(item), item.title))
        sys.stdout.flush()
        try:
            answer = sys.stdin.readline()
        except (OSError, ValueError):
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("not removed")
            return 1
    with txn(ctx) as tx:
        item = resolve(tx.lib.items, args.ref)
        tx.lib.remove(item)
        msg = "removed %s: %s" % (label(item), item.title)
    print(msg)


def cmd_undo(ctx, args):
    e = store_undo(ctx.cfg, force=args.force)
    print("undid `%s` (made %s)" % (e["command"], e["time"]))
    if e.get("saved"):
        print("the file as it was before restoring is saved at %s" % e["saved"])


# ---- list / show -----------------------------------------------------------

def parse_status_filter(text):
    if text is None:
        return ["to-read", "reading"]
    out = []
    for s in text.split(","):
        s = s.strip().lower()
        if s == "all":
            return list(STATUSES)
        if s not in STATUSES:
            raise UsageError("--status: must be one of: %s (got %r)" % (", ".join(STATUS_CHOICES), s))
        if s not in out:
            out.append(s)
    return out


def check_choice_flag(name, value, allowed):
    if value is not None and value not in allowed:
        raise UsageError("%s: must be one of: %s (got %r)" % (name, ", ".join(allowed), value))


def table(rows, header):
    cols = list(zip(*([header] + rows)))
    widths = [max(len(c) for c in col) for col in cols]
    out = []
    for r in [header] + rows:
        out.append("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip())
    return "\n".join(out)


def cmd_list(ctx, args):
    cfg = ctx.cfg
    statuses = parse_status_filter(args.status)
    check_choice_flag("--type", args.type, cfgmod.TYPES)
    check_choice_flag("--prio", args.prio, ["1", "2", "3"])
    tag = args.tag.strip().lower() if args.tag else None
    lib = load(ctx)
    order = lib.order_index()
    far = date(9999, 12, 31)
    items = [i for i in lib.items if i.status in statuses]
    if args.type:
        items = [i for i in items if i.kind == args.type]
    if args.prio:
        items = [i for i in items if i.prio == int(args.prio)]
    if tag:
        items = [i for i in items if tag in i.tags]
    if args.search:
        q = args.search.lower()
        items = [i for i in items if q in i.title.lower() or q in (i.get("by") or "").lower()
                 or q in (i.get("note") or "").lower() or q in (i.get("tags") or "").lower()]
    sort = args.sort or "prio"
    if sort == "prio":
        key = lambda i: (i.prio, i.date("added") or far, order[id(i)])
    elif sort == "added":
        key = lambda i: (i.date("added") or far, order[id(i)])
    elif sort == "len":
        key = lambda i: (i.minutes(cfg), order[id(i)])
    else:
        key = lambda i: (i.title.lower(), order[id(i)])
    items.sort(key=key)
    if not items:
        filt = ["status=" + ",".join(statuses)]
        for name, v in (("type", args.type), ("tag", tag), ("prio", args.prio), ("search", args.search)):
            if v:
                filt.append("%s=%s" % (name, v))
        print("no items match (%s)" % ", ".join(filt))
        return
    rows = []
    for i in items:
        a = i.date("added")
        rows.append([label(i), i.status, str(i.prio), i.kind, i.title, i.get("by") or "", i.get("len") or "",
                     ("%dd" % (ctx.today - a).days) if a else "-", ",".join(i.tags)])
    print(table(rows, ["ID", "STATUS", "P", "TYPE", "TITLE", "AUTHOR", "LEN", "AGE", "TAGS"]))
    print(plural(len(items), "item"))


def cmd_show(ctx, args):
    lib = load(ctx)
    item = resolve(lib.items, args.ref)
    print("id:      %s" % (item.id or "(none)"))
    print("status:  %s" % item.status)
    print("title:   %s" % item.title)
    for k, v in sorted(item.pairs, key=lambda p: KNOWN_KEYS.index(p[0]) if p[0] in KNOWN_KEYS else 100):
        if k != "id":
            print("%-8s %s" % (k + ":", v))
    print("file:    %s" % item.doc.path)
    print("line:    %s" % item.doc.lineno(item))
    for p in item_problems(item, ctx.cfg):
        if p not in ("missing id",):
            print("problem: %s" % p)


# ---- next ------------------------------------------------------------------

def parse_time(text):
    m = re.match(r"^\s*(?:(\d+)\s*h)?\s*(?:(\d+)\s*m?)?\s*$", text or "", re.I)
    if not m or not (m.group(1) or m.group(2)):
        raise UsageError("--time: expected a duration like 30m, 2h or 1h30m (got %r)" % text)
    mins = int(m.group(1) or 0) * 60 + int(m.group(2) or 0)
    if mins < 1:
        raise UsageError("--time: must be at least 1 minute")
    return mins


def cmd_next(ctx, args):
    cfg = ctx.cfg
    t = parse_time(args.time) if args.time else None
    check_choice_flag("--type", args.type, cfgmod.TYPES)
    if not 1 <= args.count <= 10:
        raise UsageError("--count: must be between 1 and 10 (got %d)" % args.count)
    lib = load(ctx)
    tag = args.tag.strip().lower() if args.tag else None
    picks, msg = rankmod.rank(lib, cfg, ctx.today, t, tag, args.type, args.count)
    if not picks:
        print(msg or "nothing to read; add something with `nextread add`")
        return
    for n, p in enumerate(picks, 1):
        i = p.item
        extra = ", ".join(x for x in (i.get("by"), i.get("len")) if x)
        print("%d. %s  %s%s" % (n, label(i), i.title, (" (" + extra + ")") if extra else ""))
        print("   " + p.reason)
        if args.why:
            f = p.factors
            print("   score %d = priority %d + in progress %d + waiting %d + variety %d + time fit %d"
                  % (p.score, f["priority"], f["in_progress"], f["waiting"], f["variety"], f["time_fit"]))
    first = picks[0].item
    print("start it with: nextread start %s" % (first.id or '"%s"' % first.title))


# ---- check / open ----------------------------------------------------------

def diagnose(lib, cfg):
    """List of (doc, lineno, text, reason)."""
    out = []
    seen = {}
    for doc in (lib.main, lib.archive):
        for n, l in enumerate(doc.lines, 1):
            if l.kind == "bad":
                out.append((doc, n, l.raw, l.reason))
            elif l.kind == "item":
                it = l.item
                text = it.doc.raw_of(it)
                for reason in item_problems(it, cfg):
                    out.append((doc, n, text, reason))
                if it.id:
                    if it.id in seen:
                        pd, pn = seen[it.id]
                        where = "line %d" % pn if pd is doc else "line %d of %s" % (pn, os.path.basename(pd.path))
                        out.append((doc, n, text, "duplicate id %s (also %s)" % (it.id, where)))
                    else:
                        seen[it.id] = (doc, n)
    return out


def fmt_problem(lib, p):
    doc, n, text, reason = p
    prefix = "line %d" % n if doc is lib.main else "%s line %d" % (os.path.basename(doc.path), n)
    return "%s: %s: %s" % (prefix, reason, text)


def print_check(lib, cfg):
    problems = diagnose(lib, cfg)
    for p in problems:
        print(fmt_problem(lib, p))
    print("%s, %s" % (plural(len(lib.items), "item"), plural(len(problems), "problem")))
    return 1 if problems else 0


def cmd_check(ctx, args):
    cfg = ctx.cfg
    if args.fix:
        repairs = []
        with txn(ctx) as tx:
            lib = tx.lib
            taken = lib.used_ids()
            seen = set()
            for doc in (lib.main, lib.archive):
                for n, l in enumerate(doc.lines, 1):
                    it = l.item
                    if it is None:
                        continue
                    pre = "line %d" % n if doc is lib.main else "%s line %d" % (os.path.basename(doc.path), n)
                    if it.id and it.id in seen:
                        old = it.id
                        nid = lib.new_id(taken)
                        it.set("id", nid)
                        repairs.append("%s: duplicate id %s replaced with %s" % (pre, old, nid))
                    elif not it.id:
                        it.set("id", lib.new_id(taken))
                        repairs.append("%s: assigned id %s" % (pre, it.id))
                    seen.add(it.id)
                    if not it.get("added"):
                        it.set("added", ctx.today.isoformat())
                        repairs.append("%s: added missing added date %s" % (pre, ctx.today.isoformat()))
                    if it.normalise_order():
                        repairs.append("%s: put fields in standard order" % pre)
        for r in repairs:
            print("fixed " + r)
        if not repairs:
            print("nothing to fix")
    lib = load(ctx, strict=False, warn_bad=False)
    return print_check(lib, cfg)


def cmd_open(ctx, args):
    cfg = ctx.cfg
    ensure_files(ctx)
    editor = os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"
    try:
        rc = subprocess.call(shlex.split(editor) + [cfg.list_path])
    except OSError as e:
        raise IOFailure("cannot run editor %r: %s" % (editor, e.strerror or e))
    if rc != 0:
        warn("warning: editor exited with status %d" % rc)
    lib = load(ctx, strict=False, warn_bad=False)
    return print_check(lib, cfg)


# ---- stats / export --------------------------------------------------------

def cmd_stats(ctx, args):
    cfg = ctx.cfg
    if args.month and args.year:
        raise UsageError("give either --month or --year, not both")
    if args.year:
        if not re.match(r"^\d{4}$", args.year):
            raise UsageError("--year: expected YYYY, like 2026 (got %r)" % args.year)
        y = int(args.year)
        period = (date(y, 1, 1), date(y + 1, 1, 1))
        lab = str(y)
    else:
        text = args.month or "%04d-%02d" % (ctx.today.year, ctx.today.month)
        m = re.match(r"^(\d{4})-(0[1-9]|1[0-2])$", text)
        if not m:
            raise UsageError("--month: expected YYYY-MM, like 2026-10 (got %r)" % text)
        period = reports.month_bounds(int(m.group(1)), int(m.group(2)))
        lab = text
    lib = load(ctx)
    st = reports.stats(lib.items, cfg, period, ctx.today)
    print(reports.format_stats(st, lab, ctx.today))


def parse_date_flag(name, text):
    if text is None:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        raise UsageError("%s: expected YYYY-MM-DD, like 2026-10-31 (got %r)" % (name, text))
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise UsageError("%s: not a real date; expected YYYY-MM-DD (got %r)" % (name, text))


def cmd_export(ctx, args):
    cfg = ctx.cfg
    statuses = parse_status_filter(args.status) if args.status else None
    d_from = parse_date_flag("--from", args.date_from)
    d_to = parse_date_flag("--to", args.date_to)
    if d_from and d_to and d_from > d_to:
        raise UsageError("--from must not be after --to")
    if args.out and os.path.exists(args.out) and not args.force:
        raise UsageError("%s already exists; use --force to overwrite" % args.out)
    lib = load(ctx)
    items = reports.export_filter(lib.items, statuses, d_from, d_to)
    text = {"csv": reports.to_csv, "json": reports.to_json, "md": reports.to_md}[args.format](items)
    if args.out:
        write_atomic(os.path.abspath(args.out), text.encode("utf-8", errors="surrogateescape"))
        print("exported %d items to %s" % (len(items), args.out))
    else:
        sys.stdout.write(text)


# ---- parser ----------------------------------------------------------------

EXAMPLES = {
    "init": "nextread init",
    "help": "nextread help add",
    "path": "nextread path",
    "config": "nextread config\n  nextread config set add.duplicates warn",
    "demo": "nextread demo\n  nextread demo --file /tmp/try.txt",
    "add": 'nextread add "Designing Data-Intensive Applications" --by "Martin Kleppmann" --type book --tags systems,db --prio 1 --len 600p\n  nextread add https://example.com/post',
    "edit": "nextread edit k3f9 --prio 3\n  nextread edit k3f9 --clear url --tags db",
    "start": "nextread start k3f9",
    "done": 'nextread done k3f9 --rating 4 --note "great ch. 5"',
    "drop": "nextread drop k3f9 --note boring",
    "reopen": "nextread reopen k3f9",
    "rm": "nextread rm k3f9 --yes",
    "undo": "nextread undo\n  nextread undo --force",
    "list": "nextread list --tag systems --search kleppmann\n  nextread list --status all --sort title",
    "show": "nextread show k3f9",
    "next": "nextread next\n  nextread next --time 30m --count 3 --why",
    "check": "nextread check\n  nextread check --fix",
    "open": "nextread open",
    "stats": "nextread stats\n  nextread stats --month 2026-10\n  nextread stats --year 2026",
    "export": "nextread export --format csv --out reading.csv\n  nextread export --format md --status done --from 2026-01-01",
}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--file", default=argparse.SUPPRESS, metavar="PATH",
                        help="use this list file (overrides $NEXTREAD_FILE and the config file)")
    top = Parser(prog="nextread", parents=[common], description="A reading list in a plain-text file you can edit by hand.",
                 epilog="Run `nextread <command> --help` for flags and examples. Start with `nextread` or `nextread demo`.")
    top.add_argument("--version", action="version", version="nextread " + __version__)
    sub = top.add_subparsers(dest="command", metavar="<command>")

    def cmd(name, func, help_, **kw):
        p = sub.add_parser(name, parents=[common], help=help_, description=help_,
                           epilog="examples:\n  " + EXAMPLES[name], formatter_class=argparse.RawDescriptionHelpFormatter, **kw)
        p.set_defaults(func=func)
        return p

    cmd("init", cmd_init, "create the list and config files if missing")
    p = cmd("help", cmd_help, "show help for all commands or one command")
    p.add_argument("topic", nargs="?")
    cmd("path", cmd_path, "print where the list, archive, history and config live")
    p = cmd("config", cmd_config, "show effective settings, or `config set <key> <value>`")
    p.add_argument("rest", nargs="*", metavar="set KEY VALUE")
    cmd("demo", cmd_demo, "load about 40 demo items into an empty list")
    p = cmd("add", cmd_add, "add an item")
    p.add_argument("title", nargs="+", help="title, or a single URL")
    add_field_flags(p)
    p = cmd("edit", cmd_edit, "change fields of one item")
    p.add_argument("ref", help="id or title (or part of it)")
    add_field_flags(p, edit=True)
    for name, f, h in (("start", cmd_start, "start reading an item"), ("reopen", cmd_reopen, "put an item back to to-read"),
                       ("show", cmd_show, "show every field of one item")):
        p = cmd(name, f, h)
        p.add_argument("ref", help="id or title (or part of it)")
    p = cmd("done", cmd_done, "mark an item finished")
    p.add_argument("ref")
    p.add_argument("--rating", help="1 to 5")
    p.add_argument("--note", help="replace the note")
    p = cmd("drop", cmd_drop, "give up on an item")
    p.add_argument("ref")
    p.add_argument("--note", help="replace the note")
    p = cmd("rm", cmd_rm, "delete an item (asks first)")
    p.add_argument("ref")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask")
    p = cmd("undo", cmd_undo, "undo the last change (repeat to go further back)")
    p.add_argument("--force", action="store_true", help="restore even if the file was edited since")
    p = cmd("list", cmd_list, "list and find items")
    p.add_argument("--status", help="to-read, reading, done, dropped, all or a comma list (default: to-read,reading)")
    p.add_argument("--type", help="book, paper, article, video or other")
    p.add_argument("--tag")
    p.add_argument("--prio", help="1, 2 or 3")
    p.add_argument("--search", help="text in title, author, note or tags")
    p.add_argument("--sort", choices=["added", "prio", "len", "title"], help="default: prio, then oldest added")
    p = cmd("next", cmd_next, "what to read next, with a reason")
    p.add_argument("--time", help="time available now, like 30m or 1h30m")
    p.add_argument("--tag")
    p.add_argument("--type", help="book, paper, article, video or other")
    p.add_argument("--count", type=int, default=1, help="how many picks, 1-10 (default 1)")
    p.add_argument("--why", action="store_true", help="show the score breakdown")
    p = cmd("check", cmd_check, "validate the list file and report problems by line")
    p.add_argument("--fix", action="store_true", help="assign missing ids, add missing added dates, order fields")
    cmd("open", cmd_open, "edit the list in $EDITOR, then check it")
    p = cmd("stats", cmd_stats, "reading summary for a month or year")
    p.add_argument("--month", help="YYYY-MM (default: this month)")
    p.add_argument("--year", help="YYYY")
    p = cmd("export", cmd_export, "export items as csv, json or md")
    p.add_argument("--format", choices=["csv", "json", "md"], required=True)
    p.add_argument("--status", help="to-read, reading, done, dropped, all or a comma list (default: all)")
    p.add_argument("--from", dest="date_from", metavar="DATE", help="YYYY-MM-DD (done date for done items, else added)")
    p.add_argument("--to", dest="date_to", metavar="DATE", help="YYYY-MM-DD")
    p.add_argument("--out", help="write to this file instead of stdout")
    p.add_argument("--force", action="store_true", help="overwrite --out if it exists")
    return top


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")  # bytes that are not UTF-8 print as \udcXX, never crash
        except (AttributeError, ValueError):
            pass
    try:
        args = build_parser().parse_args(argv)
        if args.command is None:
            args.func = cmd_init
        cfg = cfgmod.Config.load(getattr(args, "file", None))
        ctx = Ctx(cfg, argv)
        if args.command not in ("config", "help", "path"):
            for w in cfg.warnings:
                warn("warning: " + w)
        return args.func(ctx, args) or 0
    except NextreadError as e:
        print("error: %s" % e, file=sys.stderr)
        return e.exit_code
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except OSError as e:
        print("error: %s" % (io_failure(getattr(e, "filename", None) or "I/O", e)), file=sys.stderr)
        return 3
