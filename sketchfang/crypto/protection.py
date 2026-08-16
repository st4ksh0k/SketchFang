"""
Unwrap Sketchfab ``files[].p.b`` protection blobs.

1. Decode base64 → ciphertext
2. Subtract a 24-byte schedule derived from the viewer static key
   (hex-decoded with index scramble ``(2*i % 40)``) from the first 24 bytes.
   That reveals a standard Zstd frame (magic ``28 b5 2f fd``).
3. Zstd-decompress → per-model session bytecode for the stream-cipher VM.

Sketchfab rotates the 40-char static key in viewer builds; ``unwrap_protection``
tries the current key then known predecessors, and can refresh from the live
viewer when none match (see ``key_watch``).
"""

from __future__ import annotations

import base64

# Current viewer static key (ASCII hex)
STATIC_KEY_HEX = "a71f878aee8cf5865f132e0c4011aa89061f5604"

# Older keys kept so locally cached / pre-rotation protection blobs still unwrap.
KNOWN_STATIC_KEY_HEX: tuple[str, ...] = (
    STATIC_KEY_HEX,
    "7d61ef7c7530c12cf080fafd05e603d1aa3a92c6",
    "f066fd6180203f1ed2995554e7ffc6aea4fc9747",
)

_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"

try:
    import zstandard as zstd
except ImportError:  # pragma: no cover
    zstd = None  # type: ignore


def hex_nibble(ch: int) -> int:
    if ch >= 97:  # a-f
        return ch + 10 - 97
    if ch >= 65:  # A-F
        return ch + 10 - 65
    return ch - 48


def static_key_schedule(static_hex: str = STATIC_KEY_HEX, length: int = 24) -> bytes:
    """
    Pure-Python port of the first-pass schedule built inside PROCESS().

    For each i in 0..length-1, pack two hex nibbles from the 40-char static
    key at indices (2*i % 40) and (2*i+1 % 40).
    """
    key40 = static_hex[:40].lower().encode("ascii")
    if len(key40) < 40:
        raise ValueError("static key must be at least 40 hex chars")
    out = bytearray(length)
    for i in range(length):
        a = hex_nibble(key40[(2 * i) % 40])
        b = hex_nibble(key40[(2 * i + 1) % 40])
        out[i] = ((a << 4) | b) & 0xFF
    return bytes(out)


def reveal_zstd_frame(protection: bytes, static_hex: str = STATIC_KEY_HEX) -> bytes:
    """Apply the 24-byte subtract mix → Zstd frame bytes."""
    if len(protection) < 24:
        raise ValueError("protection blob too short")
    schedule = static_key_schedule(static_hex)
    out = bytearray(protection)
    for i in range(24):
        out[i] = (out[i] - schedule[i]) & 0xFF
    return bytes(out)


def register_static_key(new_key: str, *, max_known: int = 8) -> None:
    """Update in-process STATIC_KEY_HEX / KNOWN_STATIC_KEY_HEX after a rotation."""
    global STATIC_KEY_HEX, KNOWN_STATIC_KEY_HEX
    key = new_key[:40].lower()
    if len(key) < 40:
        raise ValueError("static key must be at least 40 hex chars")
    STATIC_KEY_HEX = key
    rest = [k for k in KNOWN_STATIC_KEY_HEX if k != key]
    KNOWN_STATIC_KEY_HEX = (key, *rest)[:max_known]


def _candidate_keys(static_hex: str | None) -> list[str]:
    if static_hex is not None:
        return [static_hex]
    # Deduplicate while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for key in KNOWN_STATIC_KEY_HEX:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def unwrap_protection_b64(
    protection_b64: str,
    *,
    static_hex: str | None = None,
    max_output_size: int = 1 << 20,
    auto_refresh: bool = True,
) -> bytes:
    """Base64 `p.b` → session bytes (Zstd payload after key mix)."""
    raw = base64.b64decode(
        protection_b64.replace("\n", "").replace("\r", "").replace(" ", "")
    )
    return unwrap_protection(
        raw,
        static_hex=static_hex,
        max_output_size=max_output_size,
        auto_refresh=auto_refresh,
    )


def unwrap_protection(
    protection: bytes,
    *,
    static_hex: str | None = None,
    max_output_size: int = 1 << 20,
    auto_refresh: bool = True,
) -> bytes:
    """
    Raw `p.b` bytes → session bytes.

    Tries known static keys first. When none reveal a Zstd frame and
    ``auto_refresh`` is True (default), discovers the live viewer key,
    patches ``protection.py``, and retries.
    """
    if zstd is None:
        raise RuntimeError("Missing dependency: pip install zstandard")

    last_magic = b""
    tried = _candidate_keys(static_hex)
    for key in tried:
        frame = reveal_zstd_frame(protection, static_hex=key)
        last_magic = frame[:4]
        if frame[:4] != _ZSTD_MAGIC:
            continue
        return zstd.ZstdDecompressor().decompress(
            frame, max_output_size=max_output_size
        )

    if auto_refresh and static_hex is None:
        # Local import avoids a cycle at module load (key_watch → protection).
        from .key_watch import refresh_static_key

        refresh_static_key(protection, progress=True)
        frame = reveal_zstd_frame(protection, static_hex=STATIC_KEY_HEX)
        if frame[:4] == _ZSTD_MAGIC:
            return zstd.ZstdDecompressor().decompress(
                frame, max_output_size=max_output_size
            )
        last_magic = frame[:4]
        tried = _candidate_keys(None)

    raise ValueError(
        f"after key-mix expected Zstd magic, got {last_magic.hex()} "
        f"(tried {len(tried)} static key(s))"
    )
