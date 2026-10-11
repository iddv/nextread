"""Settings: definitions, the commented config file, and path resolution."""
import os
import re
import sys

from .errors import UsageError, io_failure

ENV_FILE = "NEXTREAD_FILE"
ENV_CONFIG = "NEXTREAD_CONFIG"
TYPES = ["book", "paper", "article", "video", "other"]


class Setting(object):
    def __init__(self, key, kind, default, doc, choices=None, lo=None, hi=None, env=None):
        self.env = env  # environment variable that overrides the config file everywhere
        self.key = key
        self.kind = kind  # choice | int | float | path
        self.default = default
        self.doc = doc
        self.choices = choices
        self.lo = lo
        self.hi = hi

    def parse(self, text):
        text = text.strip()
        if self.kind == "choice":
            if text not in self.choices:
                raise ValueError("%s must be one of: %s" % (self.key, ", ".join(self.choices)))
            return text
        if self.kind in ("int", "float"):
            try:
                val = int(text) if self.kind == "int" else float(text)
            except ValueError:
                raise ValueError("%s must be a number (got %r)" % (self.key, text))
            if (self.lo is not None and val < self.lo) or (self.hi is not None and val > self.hi):
                raise ValueError("%s must be between %s and %s" % (self.key, self.lo, self.hi))
            return val
        if not text:
            raise ValueError("%s must not be empty" % self.key)
        return text


def _s(*a, **k):
    return Setting(*a, **k)


SETTINGS = [
    _s("file", "path", None, "Path of the reading list file (default: your user data directory)."),
    _s("add.duplicates", "choice", "reject", "Adding a duplicate is refused (reject) or saved with a warning (warn).", ["reject", "warn"]),
    _s("file.done_items", "choice", "keep", "Done and dropped items stay in the list (keep) or move to <name>.archive.txt (archive).", ["keep", "archive"]),
    _s("next.in_progress", "choice", "prefer", "Items you are reading are favoured by `next` (prefer) or left out (ignore).", ["prefer", "ignore"]),
    _s("write.order", "choice", "preserve", "New items are appended and your order kept (preserve), or item lines are sorted by status, priority, added (sort).", ["preserve", "sort"]),
    _s("reopen.clear_rating", "choice", "true", "Reopening a done item removes its rating (true) or keeps it (false).", ["true", "false"], env="REOPEN_CLEAR_RATING"),
    _s("reopen.keep_started", "choice", "true", "Reopening an item keeps its started date (true) or removes it (false).", ["true", "false"], env="REOPEN_KEEP_STARTED"),
    _s("next.variety_without_history", "choice", "none", "When nothing has been finished yet, no item gets the variety bonus (none) or every item does (all).", ["none", "all"], env="NEXT_VARIETY_WITHOUT_HISTORY"),
    _s("add.duplicates_check_archive", "choice", "true", "`add` also compares against the archive file (true) or only the list file (false).", ["true", "false"], env="ADD_DUPLICATES_CHECK_ARCHIVE"),
    _s("limits.title", "int", 300, "Longest allowed title, in characters.", lo=1, hi=10000),
    _s("limits.note", "int", 500, "Longest allowed note, in characters.", lo=1, hi=10000),
    _s("limits.tags", "int", 10, "Most tags per item.", lo=1, hi=100),
    _s("len.page_minutes", "int", 2, "Minutes of reading per page.", lo=1, hi=60),
    _s("len.default.article", "int", 15, "Assumed minutes for an article without len.", lo=1, hi=5000),
    _s("len.default.paper", "int", 45, "Assumed minutes for a paper without len.", lo=1, hi=5000),
    _s("len.default.video", "int", 30, "Assumed minutes for a video without len.", lo=1, hi=5000),
    _s("len.default.book", "int", 600, "Assumed minutes for a book without len.", lo=1, hi=5000),
    _s("len.default.other", "int", 30, "Assumed minutes for an item of type other without len.", lo=1, hi=5000),
    _s("next.weight.prio1", "int", 30, "`next` score for priority 1.", lo=0, hi=1000),
    _s("next.weight.prio2", "int", 15, "`next` score for priority 2.", lo=0, hi=1000),
    _s("next.weight.prio3", "int", 0, "`next` score for priority 3.", lo=0, hi=1000),
    _s("next.weight.week", "int", 1, "`next` points per full week since added.", lo=0, hi=1000),
    _s("next.weight.week_cap", "int", 20, "Most points the waiting factor can give.", lo=0, hi=1000),
    _s("next.weight.in_progress", "int", 25, "`next` bonus for items being read (when in_progress = prefer).", lo=0, hi=1000),
    _s("next.weight.time_fit", "int", 20, "`next` bonus for items that fit --time.", lo=0, hi=1000),
    _s("next.weight.variety", "int", 10, "`next` bonus when the type differs from the last finished item.", lo=0, hi=1000),
    _s("history.size", "int", 50, "How many undo snapshots to keep.", lo=1, hi=100000),
    _s("lock.timeout", "float", 5, "Seconds to wait for another Nextread process before failing with 'list is busy'.", lo=0, hi=3600),
]
BY_KEY = dict((s.key, s) for s in SETTINGS)


def platform_dirs(env=None):
    env = os.environ if env is None else env
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        base = os.path.join(env.get("APPDATA") or os.path.join(home, "AppData", "Roaming"), "nextread")
        return base, base
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Application Support", "nextread")
        return base, base
    data = os.path.join(env.get("XDG_DATA_HOME") or os.path.join(home, ".local", "share"), "nextread")
    conf = os.path.join(env.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "nextread")
    return data, conf


class Config(object):
    def __init__(self):
        self.values = {}
        self.sources = {}
        self.config_path = None
        self.config_source = "default"
        self.warnings = []

    def __getitem__(self, key):
        return self.values[key]

    # derived paths
    @property
    def list_path(self):
        return self.values["file"]

    @property
    def archive_path(self):
        base, ext = os.path.splitext(self.list_path)
        return base + ".archive.txt"

    @property
    def history_dir(self):
        return self.list_path + ".history"

    @property
    def lock_path(self):
        return self.list_path + ".lock"

    @classmethod
    def load(cls, file_flag=None, env=None):
        env = os.environ if env is None else env
        cfg = cls()
        data_dir, conf_dir = platform_dirs(env)
        default_file = os.path.join(data_dir, "reading.txt")
        for s in SETTINGS:
            cfg.values[s.key] = s.default
            cfg.sources[s.key] = "default"
        cfg.values["file"] = default_file
        if env.get(ENV_CONFIG):
            cfg.config_path = os.path.abspath(os.path.expanduser(env[ENV_CONFIG]))
            cfg.config_source = "env " + ENV_CONFIG
        else:
            cfg.config_path = os.path.join(conf_dir, "config")
        cfg._read_file()
        for s in SETTINGS:
            if s.env and env.get(s.env):
                try:
                    cfg.values[s.key] = s.parse(env[s.env])
                except ValueError as e:
                    raise UsageError("$%s: %s" % (s.env, e))
                cfg.sources[s.key] = "env " + s.env
        if env.get(ENV_FILE):
            cfg.values["file"] = env[ENV_FILE]
            cfg.sources["file"] = "env " + ENV_FILE
        if file_flag:
            cfg.values["file"] = file_flag
            cfg.sources["file"] = "--file"
        cfg.values["file"] = os.path.abspath(os.path.expanduser(cfg.values["file"]))
        cfg.default_file = default_file
        return cfg

    def _read_file(self):
        try:
            with open(self.config_path, "r", encoding="utf-8") as fh:
                lines = fh.read().splitlines()
        except FileNotFoundError:
            return
        except OSError as e:
            raise io_failure(self.config_path, e)
        for n, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = re.match(r"^([A-Za-z0-9_.]+)\s*=\s*(.*)$", line)
            if not m:
                raise UsageError("%s line %d: expected 'key = value': %s" % (self.config_path, n, line))
            key, val = m.group(1), m.group(2).strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
                val = val[1:-1]
            if key not in BY_KEY:
                self.warnings.append("%s line %d: unknown setting %r ignored" % (self.config_path, n, key))
                continue
            try:
                self.values[key] = BY_KEY[key].parse(val)
            except ValueError as e:
                raise UsageError("%s line %d: %s" % (self.config_path, n, e))
            self.sources[key] = "config"


def default_config_text(default_file):
    out = [
        "# Nextread configuration. Every setting is shown with its default.",
        "# Remove the leading '#' and edit the value to change it, or use `nextread config set <key> <value>`.",
        "# Precedence for the list path: --file, then $NEXTREAD_FILE, then 'file' here.",
        "",
    ]
    for s in SETTINGS:
        out.append("# " + s.doc)
        if s.choices:
            out.append("# values: " + ", ".join(s.choices))
        default = default_file if s.key == "file" else s.default
        out.append("# %s = %s" % (s.key, default))
        out.append("")
    return "\n".join(out)


def ensure_config_file(cfg):
    """Create the commented config file if missing. Returns True when created."""
    from .store import write_atomic
    if os.path.exists(cfg.config_path):
        return False
    write_atomic(cfg.config_path, default_config_text(cfg.default_file).encode("utf-8"))
    return True


def set_config_value(cfg, key, text):
    from .store import write_atomic
    if key not in BY_KEY:
        raise UsageError("unknown setting %r; run `nextread config` to see them" % key)
    try:
        value = BY_KEY[key].parse(text)
    except ValueError as e:
        raise UsageError(str(e))
    ensure_config_file(cfg)
    with open(cfg.config_path, "r", encoding="utf-8") as fh:
        lines = fh.read().split("\n")
    new = "%s = %s" % (key, value)
    active = re.compile(r"^\s*%s\s*=" % re.escape(key))
    commented = re.compile(r"^#\s*%s\s*=" % re.escape(key))
    for rx in (active, commented):
        for i, line in enumerate(lines):
            if rx.match(line):
                lines[i] = new
                break
        else:
            continue
        break
    else:
        while lines and lines[-1] == "":
            lines.pop()
        lines += [new, ""]
    write_atomic(cfg.config_path, "\n".join(lines).encode("utf-8"))
    return value
