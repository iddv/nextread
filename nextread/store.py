"""Reading and writing the list: lock, atomic writes, conflict detection, undo history."""
import hashlib
import json
import os
import secrets
import tempfile
import time

from .errors import BusyError, ConflictError, IOFailure, NextreadError, UsageError, io_failure
from .model import FORMAT, HEADER, Document, Item

ID_CHARS = "0123456789abcdefghijklmnopqrstuvwxyz"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_bytes(path):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except FileNotFoundError:
        return None
    except OSError as e:
        raise io_failure(path, e)


def make_dirs(path):
    try:
        os.makedirs(path, mode=0o700, exist_ok=True)
    except OSError as e:
        raise io_failure(path, e)


def write_atomic(path, data):
    """Temp file in the same directory, flushed, then renamed over the original."""
    d = os.path.dirname(path) or "."
    make_dirs(d)
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        mode = 0o600
    except OSError as e:
        raise io_failure(path, e)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(dir=d, prefix="." + os.path.basename(path) + ".", suffix=".tmp")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        try:
            os.chmod(tmp, mode)
        except OSError:
            pass
        os.replace(tmp, path)
        tmp = None
        try:
            dfd = os.open(d, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    except OSError as e:
        raise io_failure(path, e)
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


class Lock(object):
    def __init__(self, path, timeout):
        self.path = path
        self.timeout = timeout
        self.held = False

    def _stale(self):
        try:
            st = os.stat(self.path)
            with open(self.path, "r") as fh:
                pid = int(fh.read().strip() or 0)
        except (OSError, ValueError):
            try:
                return time.time() - os.stat(self.path).st_mtime > 30
            except OSError:
                return False
        if os.name == "posix" and pid > 0:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            except OSError:
                return False
            return False
        return time.time() - st.st_mtime > 120

    def acquire(self):
        make_dirs(os.path.dirname(self.path))
        deadline = time.monotonic() + self.timeout
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                self.held = True
                return
            except FileExistsError:
                if self._stale():
                    try:
                        os.unlink(self.path)
                    except OSError:
                        pass
                    continue
                if time.monotonic() >= deadline:
                    raise BusyError("list is busy (another nextread holds %s)" % self.path)
                time.sleep(0.05)
            except OSError as e:
                raise io_failure(self.path, e)

    def release(self):
        if self.held:
            self.held = False
            try:
                os.unlink(self.path)
            except OSError:
                pass


class Library(object):
    """The list file plus its optional archive, read as one collection."""

    def __init__(self, cfg, main, archive):
        self.cfg = cfg
        self.main = main
        self.archive = archive

    @classmethod
    def load(cls, cfg, strict=True):
        raw_main = read_bytes(cfg.list_path)
        raw_arch = read_bytes(cfg.archive_path)
        lib = cls(cfg, Document(cfg.list_path, raw_main), Document(cfg.archive_path, raw_arch))
        lib.raw = {"main": raw_main, "archive": raw_arch}
        if strict:
            for doc in (lib.main, lib.archive):
                if not doc.looks_like_list():
                    nb = len([l for l in doc.lines if l.kind != "blank"])
                    raise UsageError("%s does not look like a Nextread list (%d of %d lines not understood); leaving it alone"
                                     % (doc.path, len(doc.bad_lines), nb))
        return lib

    @property
    def items(self):
        """Every item once: an id present in both files counts only for the list file."""
        main = self.main.items
        ids = set(i.id for i in main if i.id)
        return main + [i for i in self.archive.items if not (i.id and i.id in ids)]

    @property
    def bad_count(self):
        return len(self.main.bad_lines) + len(self.archive.bad_lines)

    @property
    def readonly(self):
        return self.main.format > FORMAT or self.archive.format > FORMAT

    def order_index(self):
        return dict((id(i), n) for n, i in enumerate(self.items))

    def used_ids(self):
        return set(i.id for i in self.main.items + self.archive.items if i.id)

    def new_id(self, taken=None):
        taken = self.used_ids() if taken is None else taken
        while True:
            c = "".join(secrets.choice(ID_CHARS) for _ in range(4))
            if c not in taken:
                taken.add(c)
                return c

    def add_item(self, item):
        self.main.append_item(item)

    def to_archive(self, item):
        if item.doc is self.main:
            self.main.remove_item(item)
            self.archive.append_item(item)

    def to_main(self, item):
        if item.doc is self.archive:
            self.archive.remove_item(item)
            self.main.append_item(item)

    def remove(self, item):
        item.doc.remove_item(item)


class Transaction(object):
    """Exclusive read-modify-write of the list (and archive). Commits on clean exit."""

    def __init__(self, cfg, command, on_load=None):
        self.cfg = cfg
        self.command = command
        self.on_load = on_load
        self.lock = Lock(cfg.lock_path, cfg["lock.timeout"])
        self.lib = None
        self.changed = False

    def __enter__(self):
        self.lock.acquire()
        try:
            self.lib = Library.load(self.cfg)
            if self.lib.readonly:
                raise UsageError("%s uses a newer format than this version understands; opened read-only"
                                 % self.cfg.list_path)
            if self.on_load:
                self.on_load(self.lib)
            if self.lib.raw["main"] is None:
                self.lib.main.ensure_header()
                self.lib.virtual_main = self.lib.main.render()
        except BaseException:
            self.lock.release()
            raise
        return self

    def __exit__(self, et, ev, tb):
        try:
            if et is None:
                self._commit()
        finally:
            self.lock.release()
        return False

    def _commit(self):
        lib, cfg = self.lib, self.cfg
        for doc in (lib.main, lib.archive):
            doc.upgrade_header()
            if cfg["write.order"] == "sort":
                doc.sort_items()
        files = {}
        for name, doc, path in (("main", lib.main, cfg.list_path), ("archive", lib.archive, cfg.archive_path)):
            new = doc.render()
            old = lib.raw[name]
            if name == "main" and old is None:
                old_for_history = getattr(lib, "virtual_main", b"")
                if new != old_for_history:
                    files[name] = (path, old_for_history, new, True)
            elif name == "archive" and old is None:
                if lib.archive.lines:
                    files[name] = (path, None, new, True)
            elif new != old:
                files[name] = (path, old, new, False)
        if not files:
            return
        # conflict check: someone else changed a file since we read it
        for name, (path, _, _, _) in files.items():
            if read_bytes(path) != lib.raw[name]:
                raise ConflictError("file changed while working; nothing written, run again")
        # also guard the file we did not rewrite
        for name, path in (("main", cfg.list_path), ("archive", cfg.archive_path)):
            if name not in files and read_bytes(path) != lib.raw[name]:
                raise ConflictError("file changed while working; nothing written, run again")
        record_history(cfg, self.command, files)
        for name in ("main", "archive"):
            if name in files:
                path, _, new, _ = files[name]
                write_atomic(path, new)
        self.changed = True


def transaction(cfg, command, on_load=None):
    return Transaction(cfg, command, on_load)


# ---- undo history ----------------------------------------------------------

def _entries(cfg):
    d = cfg.history_dir
    try:
        names = sorted(n for n in os.listdir(d) if n.endswith(".json"))
    except FileNotFoundError:
        return []
    except OSError as e:
        raise io_failure(d, e)
    out = []
    for n in names:
        try:
            with open(os.path.join(d, n), "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            meta["_name"] = n[:-5]
            out.append(meta)
        except (OSError, ValueError):
            continue
    return out


def record_history(cfg, command, files):
    d = cfg.history_dir
    make_dirs(d)
    entries = _entries(cfg)
    seq = (entries[-1]["seq"] + 1) if entries else 1
    name = "%08d" % seq
    meta = {"seq": seq, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "command": command, "files": {}}
    for fname, (path, old, new, _) in files.items():
        snap = None
        if old is not None:
            snap = "%s.%s" % (name, fname)
            write_atomic(os.path.join(d, snap), old)
        meta["files"][fname] = {"path": path, "before": snap, "after": sha(new)}
    write_atomic(os.path.join(d, name + ".json"), json.dumps(meta, indent=1).encode("utf-8"))
    entries.append(dict(meta, _name=name))
    for e in entries[:-cfg["history.size"]]:
        _drop_entry(cfg, e)


def _drop_entry(cfg, e):
    d = cfg.history_dir
    for f in e["files"].values():
        if f["before"]:
            try:
                os.unlink(os.path.join(d, f["before"]))
            except OSError:
                pass
    try:
        os.unlink(os.path.join(d, e["_name"] + ".json"))
    except OSError:
        pass


def history_entries(cfg):
    return _entries(cfg)


def undo(cfg, force=False):
    """Restore the files to before the latest recorded change. Returns the entry undone."""
    lock = Lock(cfg.lock_path, cfg["lock.timeout"])
    lock.acquire()
    try:
        entries = _entries(cfg)
        if not entries:
            raise UsageError("nothing to undo")
        e = entries[-1]
        d = cfg.history_dir
        edited = []
        for fname, f in e["files"].items():
            cur = read_bytes(f["path"])
            if cur is None or sha(cur) != f["after"]:
                edited.append((f["path"], cur))
        saved = None
        if edited:
            if not force:
                raise ConflictError("file edited since; use `--force` to restore anyway")
            sdir = os.path.join(d, "saved")
            make_dirs(sdir)
            for path, cur in edited:
                if cur is not None:
                    saved = os.path.join(sdir, "%s-%s" % (time.strftime("%Y%m%d-%H%M%S"), os.path.basename(path)))
                    write_atomic(saved, cur)
            for old in sorted(os.listdir(sdir))[:-cfg["history.size"]]:
                try:
                    os.unlink(os.path.join(sdir, old))
                except OSError:
                    pass
        snaps = {}
        for fname, f in e["files"].items():
            if f["before"]:
                data = read_bytes(os.path.join(d, f["before"]))
                if data is None:
                    raise IOFailure("%s: history snapshot is missing" % os.path.join(d, f["before"]))
                snaps[fname] = data
        for fname, f in e["files"].items():
            if f["before"]:
                write_atomic(f["path"], snaps[fname])
            else:
                try:
                    os.unlink(f["path"])
                except FileNotFoundError:
                    pass
                except OSError as ex:
                    raise io_failure(f["path"], ex)
        _drop_entry(cfg, e)
        e["saved"] = saved
        return e
    finally:
        lock.release()
