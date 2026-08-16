"""Turn the `/textures` payload into the CDN variants worth downloading."""

from __future__ import annotations

import os
from typing import Any, Iterable
from urllib.parse import urlparse

from .models import MIME_BY_EXT, TextureInfo


def _iter_listing_entries(listing: Any) -> Iterable[dict]:
    if listing is None:
        return
    if isinstance(listing, list):
        for t in listing:
            if isinstance(t, dict):
                yield t
        return
    if isinstance(listing, dict):
        results = listing.get("results")
        if isinstance(results, list):
            for t in results:
                if isinstance(t, dict):
                    yield t
            return
        for t in listing.values():
            if isinstance(t, dict) and "images" in t:
                yield t


def ext_from_url(url: str) -> str:
    path = urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    return ext if ext in MIME_BY_EXT else ".jpg"


def best_image(images: list) -> dict | None:
    """
    Pick the CDN variant the viewer would actually upload.

    When `pk` is set the GPU unscrambler works on 8×8 tiles, so prefer
    dimensions divisible by 8 (processed RGB mips) over odd-sized originals.
    """
    usable = [i for i in images if isinstance(i, dict) and i.get("url")]
    if not usable:
        return None

    def score(im: dict) -> tuple:
        url = str(im.get("url") or "")
        ext = ext_from_url(url)
        fmt_rank = 0 if ext in {".png", ".jpg", ".jpeg", ".webp"} else -1
        opts = im.get("options") or {}
        fmt = str(opts.get("format") or "").upper()
        # Explicit RGB/RGBA processed variants over empty-options originals
        if fmt in ("RGB", "RGBA"):
            rgb_rank = 2
        elif fmt in ("",):
            rgb_rank = 1
        else:
            rgb_rank = 0  # R / single-channel mips
        w = int(im.get("width") or 0)
        h = int(im.get("height") or 0)
        tile_ok = 1 if (w % 8 == 0 and h % 8 == 0 and w >= 8 and h >= 8) else 0
        has_pk = 1 if im.get("pk") is not None else 0
        area = w * h
        size = int(im.get("size") or 0)
        return (fmt_rank, rgb_rank, tile_ok, has_pk, area, size)

    return max(usable, key=score)


def parse_texture_listing(listing: Any) -> list[TextureInfo]:
    out: list[TextureInfo] = []
    seen: set[str] = set()
    for tex in _iter_listing_entries(listing):
        uid = str(tex.get("uid") or "").lower()
        if not uid or uid in seen:
            continue
        best = best_image(tex.get("images") or [])
        if not best:
            continue
        url = str(best["url"])
        pk_raw = best.get("pk")
        pk = int(pk_raw) if pk_raw is not None else None
        seen.add(uid)
        out.append(
            TextureInfo(
                uid=uid,
                name=str(tex.get("name") or uid),
                url=url,
                width=int(best.get("width") or 0),
                height=int(best.get("height") or 0),
                ext=ext_from_url(url),
                pk=pk,
            )
        )
    return out
