"""Byte and path helpers."""

from __future__ import annotations


def pad4(data: bytes, pad: bytes = b"\x00") -> bytes:
    """Pad to a 4-byte boundary, as GLB chunks and buffer views require."""
    rem = len(data) % 4
    return data if rem == 0 else data + pad * (4 - rem)
