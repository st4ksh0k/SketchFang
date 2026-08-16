"""
Shared HTTP access for every Sketchfab endpoint.

One place owns the browser headers, timeouts, and download progress so the
endpoint modules stay one-liners.
"""

from __future__ import annotations

from typing import Any

from ..util.log import log

try:
    import requests
except ImportError:  # optional so pure-decode work needs no network stack
    requests = None  # type: ignore

API_ROOT = "https://sketchfab.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
}
REFERER_HEADERS = {**HEADERS, "Referer": f"{API_ROOT}/"}


def require_requests():
    if requests is None:
        raise RuntimeError("Missing dependency: pip install requests")
    return requests


def _headers(referer: bool) -> dict[str, str]:
    return REFERER_HEADERS if referer else HEADERS


def get_json(url: str, *, timeout: int = 30, referer: bool = False) -> Any:
    rq = require_requests()
    r = rq.get(url, headers=_headers(referer), timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_bytes(url: str, *, timeout: int = 60, referer: bool = True) -> bytes:
    """Small one-shot download (textures)."""
    rq = require_requests()
    r = rq.get(url, headers=_headers(referer), timeout=timeout)
    r.raise_for_status()
    return r.content


def download_bytes(
    url: str,
    *,
    progress: bool = True,
    label: str = "file",
    timeout: int = 120,
) -> bytes:
    """Streamed download with periodic progress (model streams)."""
    rq = require_requests()
    if progress:
        log(f"[*] Downloading {label} ...")
    r = rq.get(url, headers=REFERER_HEADERS, timeout=timeout, stream=True)
    r.raise_for_status()
    total = int(r.headers.get("Content-Length", 0))
    chunks: list[bytes] = []
    done = 0
    for chunk in r.iter_content(65536):
        if not chunk:
            continue
        chunks.append(chunk)
        done += len(chunk)
        if progress and total and done % (256 * 1024) < 65536:
            log(f"[*] {label}: {done:,}/{total:,} ({100 * done // total}%)")
    data = b"".join(chunks)
    if progress:
        log(f"[*] Downloaded {label}: {len(data):,} bytes")
    return data
