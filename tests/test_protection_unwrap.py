"""protection.b unwrap: static-key mix reveals Zstd (no WASM)."""

from __future__ import annotations

import base64
from pathlib import Path

import pytest

from sketchfang.crypto.protection import (
    KNOWN_STATIC_KEY_HEX,
    reveal_zstd_frame,
    static_key_schedule,
    unwrap_protection,
)

PROBE = Path(__file__).resolve().parents[1] / ".probe"
SAMPLE_UID = "e3c3072cab4b4ef2ba8bc796f588d1ef"


@pytest.mark.skipif(
    not (PROBE / f"{SAMPLE_UID}.protection.b64").is_file(),
    reason="no local .probe sample; run scripts/binz_probe.py first",
)
def test_unwrap_matches_probe_session():
    b64 = (PROBE / f"{SAMPLE_UID}.protection.b64").read_text().strip()
    expected = (PROBE / f"{SAMPLE_UID}.session.bin").read_bytes()
    prot = base64.b64decode(b64)
    # Cached probes may predate a viewer key rotation; try known keys.
    frame = None
    for key in KNOWN_STATIC_KEY_HEX:
        candidate = reveal_zstd_frame(prot, static_hex=key)
        if candidate[:4] == b"\x28\xb5\x2f\xfd":
            frame = candidate
            break
    assert frame is not None
    assert unwrap_protection(prot) == expected


def test_schedule_is_deterministic_and_wraps():
    from sketchfang.crypto.protection import STATIC_KEY_HEX

    s = static_key_schedule()
    assert len(s) == 24
    # 40 hex chars → 20 bytes; schedule length 24 wraps the first 4 again
    assert s[:4] == s[20:24]
    assert s.hex().startswith(STATIC_KEY_HEX[:8])
