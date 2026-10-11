"""Demo list: 40 items, all statuses, dates relative to today. Loaded only by `nextread demo`."""
import calendar
import random
from datetime import date, timedelta

from .model import MARK_OF, Item, esc

A = "https://arxiv.org/abs/"
# (type, title, by, tags, prio, len, added_days_ago, url, state)
# state: "todo" | ("read", started_days_ago) | ("done", month_offset, day, days_taken, rating[, note]) | ("drop", days_ago, note)
D = [
    ("book", "Designing Data-Intensive Applications", "Martin Kleppmann", "systems, db", 1, "600p", 150, None, "todo"),
    ("book", "The Pragmatic Programmer", "Andrew Hunt, David Thomas", "craft", 2, "352p", 120, None, ("done", 0, 4, 21, 5, "Still the best advice on craft.")),
    ("book", "Thinking, Fast and Slow", "Daniel Kahneman", "psychology", 3, "499p", 170, None, "todo"),
    ("book", "The Mythical Man-Month", "Frederick P. Brooks Jr.", "management, craft", 2, "322p", 160, None, ("done", 2, 12, 30, 4)),
    ("book", "Staff Engineer", "Will Larson", "career, management", 1, "300p", 40, None, "todo"),
    ("book", "A Philosophy of Software Design", "John Ousterhout", "craft, design", 1, "190p", 100, None, ("done", 1, 9, 12, 5)),
    ("book", "Structure and Interpretation of Computer Programs", "Harold Abelson, Gerald Jay Sussman", "cs, lisp", 3, "657p", 175, None, "todo"),
    ("book", "The Soul of a New Machine", "Tracy Kidder", "history, hardware", 2, "293p", 140, None, ("done", 2, 20, 17, 4)),
    ("book", "Deep Work", "Cal Newport", "productivity", 3, "296p", 130, None, ("drop", 35, "Too repetitive.")),
    ("book", "Seeing Like a State", "James C. Scott", "politics, history", 3, "464p", 165, None, ("drop", 60, "Not now.")),
    ("book", "The Dispossessed", "Ursula K. Le Guin", "fiction", 2, "387p", 25, None, "todo"),
    ("book", "Godel, Escher, Bach", "Douglas Hofstadter", "cs, math", 2, "777p", 90, None, "todo"),
    ("book", "Crafting Interpreters", "Robert Nystrom", "compilers, cs", 1, "640p", 80, "https://craftinginterpreters.com/", ("read", 18)),
    ("book", "The Design of Everyday Things", "Don Norman", "design", 2, "368p", 55, None, "todo"),
    ("book", "Software Engineering at Google", "Titus Winters, Tom Manshreck, Hyrum Wright", "craft, management", 3, "599p", 70, None, "todo"),
    ("paper", "Attention Is All You Need", "Ashish Vaswani et al.", "ml", 1, "15p", 60, A + "1706.03762", "todo"),
    ("paper", "The Google File System", "Sanjay Ghemawat, Howard Gobioff, Shun-Tak Leung", "systems, db", 2, "15p", 110, None, ("done", 0, 6, 3, 4)),
    ("paper", "MapReduce: Simplified Data Processing on Large Clusters", "Jeffrey Dean, Sanjay Ghemawat", "systems", 2, "13p", 115, None, ("done", 1, 15, 2, 3)),
    ("paper", "Dynamo: Amazon's Highly Available Key-value Store", "Giuseppe DeCandia et al.", "systems, db", 1, "16p", 95, None, "todo"),
    ("paper", "Time, Clocks, and the Ordering of Events in a Distributed System", "Leslie Lamport", "systems, theory", 2, "8p", 150, None, ("done", 2, 3, 4, 5)),
    ("paper", "In Search of an Understandable Consensus Algorithm", "Diego Ongaro, John Ousterhout", "systems", 1, "18p", 45, None, "todo"),
    ("paper", "A Relational Model of Data for Large Shared Data Banks", "E. F. Codd", "db, theory", 3, "11p", 85, None, "todo"),
    ("paper", "No Silver Bullet", "Frederick P. Brooks Jr.", "craft", 2, "16p", 30, None, "todo"),
    ("paper", "Out of the Tar Pit", "Ben Moseley, Peter Marks", "design, craft", 2, "66p", 50, None, ("read", 9)),
    ("paper", "Reflections on Trusting Trust", "Ken Thompson", "security", 3, "3p", 100, None, ("done", 2, 27, 1, 5)),
    ("article", "Parse, don't validate", "Alexis King", "craft, types", 1, "20m", 35, "https://lexi-lambda.github.io/blog/2019/11/05/parse-don-t-validate/", ("done", 0, 2, 1, 5)),
    ("article", "The Joel Test: 12 Steps to Better Code", "Joel Spolsky", "management", 3, "10m", 125, "https://www.joelonsoftware.com/2000/08/09/the-joel-test-12-steps-to-better-code/", ("done", 1, 21, 1, 3)),
    ("article", "Choose Boring Technology", "Dan McKinley", "craft, management", 2, "15m", 105, None, ("done", 2, 8, 1, 4)),
    ("article", "The Log: What every software engineer should know", "Jay Kreps", "systems, db", 1, "45m", 12, None, "todo"),
    ("article", "How to Do Great Work", "Paul Graham", "career", 2, "40m", 8, None, "todo"),
    ("article", "Things You Should Never Do, Part I", "Joel Spolsky", "craft", 2, "10m", 135, None, ("done", 0, 1, 2, 4)),
    ("article", "The Rise of Worse is Better", "Richard P. Gabriel", "design, history", 3, "10m", 75, None, "todo"),
    ("article", "Notes on structured concurrency", "Nathaniel J. Smith", "concurrency", 3, "50m", 145, None, ("drop", 20, "Not using Python much now.")),
    ("article", "The Grug Brained Developer", "grug", "craft, humour", 3, "30m", 15, None, "todo"),
    ("article", "Falsehoods programmers believe about time", "Noah Sussman", "craft", 2, "15m", 65, None, "todo"),
    ("article", "Local-first software", "Martin Kleppmann et al.", "systems, design", 1, "60m", 28, "https://www.inkandswitch.com/local-first/", ("read", 5)),
    ("article", "A Plan for Spam", "Paul Graham", "ml, history", 3, "25m", 180, None, "todo"),
    ("video", "Simple Made Easy", "Rich Hickey", "design, craft", 1, "61m", 42, None, ("read", 2)),
    ("video", "The Mess We're In", "Joe Armstrong", "systems, craft", 2, "45m", 18, None, "todo"),
    ("video", "Growing a Language", "Guy Steele", "cs, design", 2, "55m", 95, None, ("done", 0, 3, 1, 4)),
]

MALFORMED = "[?] The Pragmatic Programmer, second edition | by: Hunt & Thomas | type: book"


def _month_day(today, offset, day):
    y, m = today.year, today.month - offset
    while m < 1:
        m += 12
        y -= 1
    last = today.day if offset == 0 else calendar.monthrange(y, m)[1]
    return date(y, m, min(day, last))


def demo_lines(today, ids=None):
    """Returns the lines of the demo list (header comments excluded)."""
    rnd = random.Random(2026)
    used = set()

    def new_id():
        while True:
            c = "".join(rnd.choice("0123456789abcdefghijklmnopqrstuvwxyz") for _ in range(4))
            if c not in used:
                used.add(c)
                return c

    items = []
    for kind, title, by, tags, prio, ln, ago, url, state in D:
        added = today - timedelta(days=ago)
        pairs = [["by", by], ["type", kind], ["tags", tags], ["prio", str(prio)], ["len", ln]]
        if url:
            pairs.append(["url", url])
        status = "to-read"
        extra = []
        if state != "todo":
            if state[0] == "read":
                status = "reading"
                started = today - timedelta(days=state[1])
                added = min(added, started)
                extra = [["added", None], ["started", started.isoformat()]]
            elif state[0] == "done":
                status = "done"
                done = _month_day(today, state[1], state[2])
                started = done - timedelta(days=state[3])
                added = min(added, started - timedelta(days=2))
                extra = [["added", None], ["started", started.isoformat()], ["done", done.isoformat()], ["rating", str(state[4])]]
                if len(state) > 5:
                    pairs.append(["note", state[5]])
            else:
                status = "dropped"
                dropped = today - timedelta(days=state[1])
                added = min(added, dropped - timedelta(days=5))
                extra = [["added", None], ["dropped", dropped.isoformat()]]
                pairs.append(["note", state[2]])
        if not extra:
            extra = [["added", None]]
        for k, v in extra:
            pairs.append([k, added.isoformat() if k == "added" else v])
        pairs.append(["id", new_id()])
        items.append(Item(status, title, pairs, None, True))
    lines = [
        "# Demo data: 40 items. Delete this file's contents or use --file to start your own list.",
    ]
    lines += [it.text() for it in items[:20]]
    lines += ["", "# A deliberately malformed line (unknown status marker) so `nextread check` has something to report:", MALFORMED, ""]
    lines += [it.text() for it in items[20:]]
    return lines
