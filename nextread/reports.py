"""`stats` and `export`."""
import csv
import io
import json
from datetime import date

from .model import KNOWN_KEYS, STATUSES

CSV_HEADER = ["id", "status", "title", "by", "type", "tags", "prio", "len", "url", "note",
              "added", "started", "done", "dropped", "rating", "extra"]


def month_bounds(y, m):
    start = date(y, m, 1)
    end = date(y + (m == 12), m % 12 + 1, 1)
    return start, end  # [start, end)


def in_period(d, period):
    return d is not None and period[0] <= d < period[1]


def stats(items, cfg, period, today):
    added = [i for i in items if in_period(i.date("added"), period)]
    done = [i for i in items if i.status == "done" and in_period(i.date("done"), period)]
    dropped = [i for i in items if i.status == "dropped" and in_period(i.date("dropped"), period)]
    by_type = {}
    for i in done:
        by_type[i.kind] = by_type.get(i.kind, 0) + 1
    pages = minutes = nolen = 0
    for i in done:
        ln = i.length
        if ln is None:
            nolen += 1
        elif ln[1] == "p":
            pages += ln[0]
            minutes += ln[0] * cfg["len.page_minutes"]
        else:
            minutes += ln[0]
    spans = []
    for i in done:
        s, d = i.date("started"), i.date("done")
        if s and d and d >= s:
            spans.append((d - s).days)
    waiting = [i for i in items if i.status == "to-read"]
    far = date(9999, 12, 31)
    order = dict((id(i), n) for n, i in enumerate(items))
    oldest = sorted(waiting, key=lambda i: (i.date("added") or far, order[id(i)]))[:3]
    return {
        "added": len(added), "done": len(done), "by_type": by_type, "pages": pages, "minutes": minutes,
        "no_len": nolen, "avg_days": (sum(spans) / float(len(spans))) if spans else None,
        "dropped": len(dropped), "backlog": len(waiting), "oldest": oldest,
    }


def format_stats(st, label, today):
    lines = ["Reading summary for %s" % label]
    lines.append("added:       %d" % st["added"])
    lines.append("finished:    %d" % st["done"])
    if st["by_type"]:
        lines.append("  by type:   " + ", ".join("%s %d" % (k, v) for k, v in sorted(st["by_type"].items())))
    lines.append("pages:       %d" % st["pages"])
    lines.append("minutes:     %d" % st["minutes"])
    if st["no_len"]:
        lines.append("  (%d finished item%s without len: counted, but no pages or minutes)"
                     % (st["no_len"], "" if st["no_len"] == 1 else "s"))
    lines.append("avg days start to done: %s" % ("%.1f" % st["avg_days"] if st["avg_days"] is not None else "n/a"))
    lines.append("dropped:     %d" % st["dropped"])
    lines.append("backlog:     %d to-read" % st["backlog"])
    if st["oldest"]:
        lines.append("oldest waiting:")
        for i in st["oldest"]:
            a = i.date("added")
            age = "%dd" % (today - a).days if a else "?"
            lines.append("  %s  %s (%s)" % (i.id or "----", i.title, age))
    return "\n".join(lines)


def export_filter(items, statuses=None, d_from=None, d_to=None):
    out = []
    for i in items:
        if statuses and i.status not in statuses:
            continue
        if d_from or d_to:
            d = i.date("done") if i.status == "done" else i.date("added")
            if d is None or (d_from and d < d_from) or (d_to and d > d_to):
                continue
        out.append(i)
    return out


def extras(item):
    return [(k, v) for k, v in item.pairs if k not in KNOWN_KEYS]


def to_csv(items):
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_HEADER)
    for i in items:
        row = [i.id, i.status, i.title]
        for k in ("by", "type", "tags", "prio", "len", "url", "note", "added", "started", "done", "dropped", "rating"):
            row.append(i.get(k) or "")
        row.append(" | ".join("%s: %s" % kv for kv in extras(i)))
        w.writerow(row)
    return buf.getvalue()


def to_json(items):
    out = []
    for i in items:
        o = {"id": i.id or None, "status": i.status, "title": i.title}
        for k in ("by", "type", "url", "note", "added", "started", "done", "dropped", "len"):
            o[k] = i.get(k) or None
        o["tags"] = i.tags
        for k in ("prio", "rating"):
            v = i.get(k)
            o[k] = int(v) if v and v.isdigit() else (v or None)
        o["extra"] = dict(extras(i))
        out.append(o)
    return json.dumps(out, indent=2, ensure_ascii=False) + "\n"


def to_md(items):
    heads = {"to-read": "To read", "reading": "Reading", "done": "Done", "dropped": "Dropped"}
    lines = ["# Reading list", ""]
    for st in STATUSES:
        group = [i for i in items if i.status == st]
        if not group:
            continue
        lines += ["## %s (%d)" % (heads[st], len(group)), ""]
        for i in group:
            box = "[x]" if st == "done" else "[ ]"
            title = "~~%s~~" % i.title if st == "dropped" else i.title
            bits = []
            for key, label in (("by", "by %s"), ("type", "%s"), ("len", "%s"), ("prio", "prio %s"),
                               ("rating", "rating %s/5"), ("added", "added %s"), ("started", "started %s"),
                               ("done", "done %s"), ("dropped", "dropped %s")):
                if i.get(key):
                    bits.append(label % i.get(key))
            if i.tags:
                bits.append("tags: " + ", ".join(i.tags))
            if i.get("url"):
                bits.append("<%s>" % i.get("url"))
            if i.get("note"):
                bits.append("note: " + i.get("note"))
            for k, v in extras(i):
                bits.append("%s: %s" % (k, v))
            if i.id:
                bits.append("id %s" % i.id)
            lines.append("- %s %s%s" % (box, title, (" - " + "; ".join(bits)) if bits else ""))
        lines.append("")
    return "\n".join(lines)
