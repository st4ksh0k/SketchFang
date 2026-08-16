"""Texture data contracts: one listing entry, one file on disk."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


@dataclass(frozen=True)
class TextureInfo:
    """A CDN image variant chosen from the texture listing."""

    uid: str
    name: str
    url: str
    width: int = 0
    height: int = 0
    ext: str = ".jpg"
    pk: int | None = None  # viewer scramble key (image.pk)


@dataclass
class TextureAsset:
    """A downloaded (and, when scrambled, decoded) image on disk."""

    uid: str
    name: str
    path: Path
    width: int = 0
    height: int = 0
    mime: str = "image/jpeg"
    pk: int | None = None
