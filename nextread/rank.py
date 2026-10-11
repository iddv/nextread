"""`next`: deterministic ranking with a one-sentence reason."""
from datetime import date

FAR = date(9999, 12, 31)
# order used to break ties between equal factors when naming the reason
FACTOR_ORDER = ["priority", "in_progress", "waiting", "variety"]


class Pick(object):
    def __init__(self, item, score, factors, reason, fits):
        self.item = item
        self.score = score
        self.factors = factors  # dict name -> points
        self.reason = reason
        self.fits = fits


def phrase_join(parts):
    if not parts:
        return ""
    if len(parts) == 1:
        s = parts[0]
    elif len(parts) == 2:
        s = "%s and %s" % tuple(parts)
    else:
        s = "%s, and %s" % (", ".join(parts[:-1]), parts[-1])
    return s[0].upper() + s[1:] + "."


def last_finished_type(items, order):
    best = None
    for it in items:
        if it.status != "done":
            continue
        d = it.date("done")
        if d is None:
            continue
        key = (d, order[id(it)])
        if best is None or key > best[0]:
            best = (key, it)
    return best[1].kind if best else None


def rank(lib, cfg, today, time_limit=None, tag=None, kind=None, count=1):
    """Returns (picks, message). `message` is None unless nothing fit the time."""
    items = lib.items
    order = dict((id(i), n) for n, i in enumerate(items))
    prefer = cfg["next.in_progress"] == "prefer"
    cands = []
    for it in items:
        if it.status == "to-read" or (it.status == "reading" and prefer):
            if tag and tag not in it.tags:
                continue
            if kind and it.kind != kind:
                continue
            cands.append(it)
    if not cands:
        return [], "nothing to read; add something with `nextread add`"
    last_type = last_finished_type(items, order)

    def sort_key(p):
        return (-p.score, p.item.date("added") or FAR, order[id(p.item)])

    scored = []
    for it in cands:
        f = {"priority": cfg["next.weight.prio%d" % it.prio], "in_progress": 0, "waiting": 0, "variety": 0}
        added = it.date("added")
        if added is not None:
            weeks = max(0, (today - added).days) // 7
            f["waiting"] = min(cfg["next.weight.week_cap"], weeks * cfg["next.weight.week"])
        else:
            weeks = 0
        if it.status == "reading" and prefer:
            f["in_progress"] = cfg["next.weight.in_progress"]
        if last_type is None:
            if cfg["next.variety_without_history"] == "all":
                f["variety"] = cfg["next.weight.variety"]
        elif it.kind != last_type:
            f["variety"] = cfg["next.weight.variety"]
        fits = time_limit is None or it.minutes(cfg) <= time_limit
        fit_pts = cfg["next.weight.time_fit"] if (time_limit is not None and fits) else 0
        score = sum(f.values()) + fit_pts
        f["time_fit"] = fit_pts
        names = {
            "priority": "Priority %d" % it.prio,
            "in_progress": "already in progress",
            "waiting": "waiting %d week%s" % (weeks, "" if weeks == 1 else "s"),
            "variety": ("a change from your last %s" % last_type) if last_type else "a fresh start",
        }
        top = sorted([n for n in FACTOR_ORDER if f[n] > 0], key=lambda n: -f[n])[:2]
        parts = [names[n] for n in top]
        if time_limit is not None and fits:
            parts.append("it fits your %d minutes" % time_limit)
        reason = phrase_join(parts) or "Nothing stands out, so the oldest waiting item comes first."
        scored.append(Pick(it, score, f, reason, fits))

    message = None
    if time_limit is not None:
        fitting = [p for p in scored if p.fits]
        if fitting:
            scored = fitting
        else:
            scored.sort(key=lambda p: (p.item.minutes(cfg), sort_key(p)))
            picks = scored[:count]
            for p in picks:
                p.reason = "nothing fits %dm; this is the shortest" % time_limit
            return picks, None
    scored.sort(key=sort_key)
    return scored[:count], message
