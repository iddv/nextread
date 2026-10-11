"""Shared helpers: run the real CLI in a subprocess against a throwaway home."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TODAY = "2026-10-11"


class CliCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="nextread-test-")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.list = os.path.join(self.tmp, "data", "reading.txt")
        self.config = os.path.join(self.tmp, "conf", "config")
        self.env = dict(os.environ)
        self.env.update({
            "NEXTREAD_FILE": self.list,
            "NEXTREAD_CONFIG": self.config,
            "NEXTREAD_TODAY": TODAY,
            "HOME": self.tmp,
            "PYTHONPATH": ROOT,
            "PYTHONDONTWRITEBYTECODE": "1",
        })
        for k in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "EDITOR", "VISUAL"):
            self.env.pop(k, None)

    def run_cli(self, *args, **kw):
        env = dict(self.env)
        env.update(kw.pop("env", {}))
        p = subprocess.run([sys.executable, "-m", "nextread"] + list(args), env=env, cwd=ROOT,
                           input=kw.pop("input", ""), capture_output=True, text=True, errors="surrogateescape", timeout=60)
        return p.returncode, p.stdout, p.stderr

    def ok(self, *args, **kw):
        rc, out, err = self.run_cli(*args, **kw)
        self.assertEqual(rc, 0, "args=%r\nstdout=%s\nstderr=%s" % (args, out, err))
        return out

    def err(self, *args, code=1, **kw):
        rc, out, err = self.run_cli(*args, **kw)
        self.assertEqual(rc, code, "args=%r\nstdout=%s\nstderr=%s" % (args, out, err))
        return err

    def write(self, text, path=None, newline=None):
        path = path or self.list
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline=newline) as fh:
            fh.write(text)

    def read(self, path=None):
        with open(path or self.list, "r", encoding="utf-8", newline="") as fh:
            return fh.read()

    def add(self, title, *flags):
        out = self.ok("add", title, *flags)
        return out.strip().splitlines()[-1].split()[-1]  # id
