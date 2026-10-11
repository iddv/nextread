"""Error types. Each carries the process exit code (see README)."""
import os


class NextreadError(Exception):
    """A plain one-line error. exit_code: 1 usage/validation, 2 conflict/busy, 3 I/O."""

    exit_code = 1


class UsageError(NextreadError):
    exit_code = 1


class ConflictError(NextreadError):
    exit_code = 2


class BusyError(NextreadError):
    exit_code = 2


class IOFailure(NextreadError):
    exit_code = 3


def io_failure(path, exc):
    reason = exc.strerror if isinstance(exc, OSError) and exc.strerror else str(exc)
    return IOFailure("%s: %s" % (path, reason))
