"""Progress output. One place, so no layer has to import another for logging."""

from __future__ import annotations

import sys


def log(msg: str) -> None:
    """Always-flush stderr progress (works even without `python -u`)."""
    print(msg, file=sys.stderr, flush=True)


def enable_line_buffering() -> None:
    """Make CLI progress appear immediately when stdout/stderr are pipes."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(line_buffering=True)  # type: ignore[attr-defined]
        except Exception:
            pass
