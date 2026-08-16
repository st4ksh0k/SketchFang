"""`GET /i/models/{uid}/textures` — raw CDN texture listing."""

from __future__ import annotations

from typing import Any

from ..util.log import log
from .client import API_ROOT, get_json

API_TEXTURES = API_ROOT + "/i/models/{uid}/textures"


def fetch_texture_list(uid: str, *, progress: bool = True) -> Any:
    url = API_TEXTURES.format(uid=uid)
    if progress:
        log(f"[*] Fetching texture listing: {url}")
    return get_json(url)
