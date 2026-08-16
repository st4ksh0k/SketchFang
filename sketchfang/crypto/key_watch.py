"""
Discover Sketchfab viewer static keys from live embed JS (in memory only).

Bundles are fetched, scanned, and discarded — never written to disk.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from ..api.client import API_ROOT, REFERER_HEADERS, require_requests
from ..util.log import log
from . import protection as prot
from .protection import register_static_key, reveal_zstd_frame

# Public model used only to load the viewer embed / webpack script list.
DEFAULT_PROBE_UID = "5644eaaea625424f94c96a4ecfd1d222"

_SCRIPT_SRC_RE = re.compile(
    r'src="(https://static\.sketchfab\.com/static/builds/web/dist/'
    r'[a-f0-9]{32}-v2\.js)"'
)
# Webpack export shapes seen in the wild:
#   t.exports="7d61ef7c…\n"
#   const n="f066fd61…\n"
_KEY_EXPORT_RE = re.compile(
    r'(?:exports\s*=\s*|const\s+\w+\s*=\s*)"([0-9a-f]{40})\\n"'
)
_KEY_NEWLINE_RE = re.compile(r'"([0-9a-f]{40})\\n"')

_PROTECTION_PY = Path(__file__).resolve().with_name("protection.py")
_MAX_KNOWN = 8


def validate_static_key(key: str, protection: bytes) -> bool:
    """True if ``key`` reveals a Zstd frame from the protection blob."""
    if len(key) < 40 or len(protection) < 24:
        return False
    try:
        frame = reveal_zstd_frame(protection, static_hex=key)
    except ValueError:
        return False
    return frame[:4] == prot._ZSTD_MAGIC


def extract_key_candidates(js_text: str) -> list[str]:
    """Prefer webpack export matches; fall back to any 40-hex-newline string."""
    seen: set[str] = set()
    out: list[str] = []
    for pattern in (_KEY_EXPORT_RE, _KEY_NEWLINE_RE):
        for key in pattern.findall(js_text):
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _fetch_text(url: str, *, timeout: int = 60) -> str:
    rq = require_requests()
    r = rq.get(url, headers=REFERER_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def iter_embed_script_urls(uid: str = DEFAULT_PROBE_UID) -> list[str]:
    html = _fetch_text(f"{API_ROOT}/models/{uid}/embed", timeout=30)
    # Preserve order; dedupe.
    seen: set[str] = set()
    urls: list[str] = []
    for url in _SCRIPT_SRC_RE.findall(html):
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def discover_static_key(
    uid: str = DEFAULT_PROBE_UID,
    *,
    protection: bytes | None = None,
    progress: bool = False,
) -> str:
    """
    Fetch embed script URLs, scan each ``-v2.js`` in memory, discard bodies.

    If ``protection`` is given, return the first candidate that validates.
    Otherwise return the first webpack-shaped candidate.
    """
    urls = iter_embed_script_urls(uid)
    if progress:
        log(f"[*] Scanning {len(urls)} viewer script(s) for static key ...")

    fallback: str | None = None
    for url in urls:
        # Keep body only for this iteration; dropped when loop continues.
        text = _fetch_text(url)
        try:
            candidates = extract_key_candidates(text)
        finally:
            del text

        for key in candidates:
            if protection is not None:
                if validate_static_key(key, protection):
                    if progress:
                        name = url.rsplit("/", 1)[-1]
                        log(f"[*] Valid static key in {name}")
                    return key
            elif fallback is None:
                fallback = key
                if progress:
                    name = url.rsplit("/", 1)[-1]
                    log(f"[*] Candidate static key in {name}")

    if protection is not None:
        raise RuntimeError(
            "no viewer static key validated against the protection blob"
        )
    if fallback is None:
        raise RuntimeError("no 40-hex static key found in viewer scripts")
    return fallback


def patch_protection_py(
    new_key: str,
    *,
    path: Path | None = None,
    max_known: int = _MAX_KNOWN,
) -> bool:
    """
    Rewrite STATIC_KEY_HEX / KNOWN_STATIC_KEY_HEX in protection.py.

    Returns True if the file changed.
    """
    path = path or _PROTECTION_PY
    key = new_key[:40].lower()
    if len(key) < 40:
        raise ValueError("static key must be at least 40 hex chars")

    text = path.read_text(encoding="utf-8")
    # Prefer keys already listed in the target file, then the live module.
    file_keys = re.findall(r'"([0-9a-fA-F]{40})"', text)
    known: list[str] = []
    for k in (key, *file_keys, prot.STATIC_KEY_HEX, *prot.KNOWN_STATIC_KEY_HEX):
        k = k[:40].lower()
        if k not in known:
            known.append(k)
    known = known[:max_known]

    rest = [k for k in known if k != key]
    known_lines = ["    STATIC_KEY_HEX,"] + [f'    "{k}",' for k in rest]
    known_block = "\n".join(known_lines)
    new_text, n_static = re.subn(
        r'^STATIC_KEY_HEX = "[0-9a-fA-F]{40}"',
        f'STATIC_KEY_HEX = "{key}"',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if n_static != 1:
        raise RuntimeError(f"could not locate STATIC_KEY_HEX in {path}")

    new_text, n_known = re.subn(
        r"KNOWN_STATIC_KEY_HEX: tuple\[str, \.\.\.\] = \(\n"
        r"(?:    (?:STATIC_KEY_HEX|\"[0-9a-fA-F]{40}\"),?\n)+"
        r"\)",
        f"KNOWN_STATIC_KEY_HEX: tuple[str, ...] = (\n{known_block}\n)",
        new_text,
        count=1,
    )
    if n_known != 1:
        raise RuntimeError(f"could not locate KNOWN_STATIC_KEY_HEX in {path}")

    if new_text == text:
        return False
    path.write_text(new_text, encoding="utf-8")
    return True


def refresh_static_key(
    protection: bytes,
    *,
    uid: str = DEFAULT_PROBE_UID,
    patch_file: bool = True,
    progress: bool = True,
) -> str:
    """
    Discover a key that unwraps ``protection``, register it in-process,
    and optionally rewrite protection.py.
    """
    if progress:
        log("[*] Viewer static key stale; discovering from Sketchfab ...")
    key = discover_static_key(uid, protection=protection, progress=progress)
    register_static_key(key)
    if patch_file:
        changed = patch_protection_py(key)
        if progress:
            if changed:
                log(f"[*] Updated protection.py → {key}")
            else:
                log(f"[*] protection.py already at {key}")
    return key


def ensure_static_key(
    protection: bytes,
    *,
    uid: str = DEFAULT_PROBE_UID,
    auto_refresh: bool = True,
    patch_file: bool = True,
    progress: bool = False,
) -> str:
    """
    Return a static key that validates against ``protection``.

    Checks known keys first (no network). On miss, discovers from the live
    viewer and patches the repo when ``auto_refresh`` is True.
    """
    for key in _unique((prot.STATIC_KEY_HEX, *prot.KNOWN_STATIC_KEY_HEX)):
        if validate_static_key(key, protection):
            return key
    if not auto_refresh:
        raise ValueError("no known static key unwraps this protection blob")
    return refresh_static_key(
        protection, uid=uid, patch_file=patch_file, progress=progress
    )


def _unique(keys: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for key in keys:
        k = key[:40].lower()
        if k not in seen:
            seen.add(k)
            out.append(k)
    return out
