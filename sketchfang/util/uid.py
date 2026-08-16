"""Sketchfab model UID parsing."""

from __future__ import annotations

import re

UID_RE = re.compile(r"([a-f0-9]{32})", re.I)


def extract_uid(url_or_uid: str) -> str:
    m = UID_RE.search(url_or_uid or "")
    if not m:
        raise ValueError(f"Could not extract a 32-char UID from {url_or_uid!r}")
    return m.group(1)


def looks_like_uid(url_or_uid: str) -> bool:
    return bool(UID_RE.search(url_or_uid or ""))
