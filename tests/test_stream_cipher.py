"""Pure-Python BINZ stream cipher (session VM + xorshift16)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sketchfang.crypto.r4cz import inflate_r4cz
from sketchfang.crypto.session_vm import decrypt_binz_with_session
from sketchfang.crypto.stream import decrypt_binz_to_r4cz
from sketchfang.crypto.xorshift import apply_xorshift16, xorshift16_step

PROBE = Path(__file__).resolve().parents[1] / ".probe"
UIDS = (
    "e3c3072cab4b4ef2ba8bc796f588d1ef",
    "9fd5d4d0b7ca424893a9da7dee1196bd",
)


def test_xorshift16_step_roundtrip_inverse():
    inv = [None] * 65536
    for s in range(65536):
        inv[xorshift16_step(s)] = s
    assert all(v is not None for v in inv)
    for s in (0, 1, 0xD2AD, 0xFFFF):
        assert inv[xorshift16_step(s)] == s


def test_apply_leaves_odd_trailing_byte():
    buf = bytearray(b"\x00\x00\xff")
    apply_xorshift16(buf, 0, 3, 0x1234)
    # only one u16 processed; last byte unchanged
    assert buf[2] == 0xFF


@pytest.mark.parametrize("uid", UIDS)
@pytest.mark.skipif(
    not (PROBE / f"{UIDS[0]}.session.bin").is_file(),
    reason="no local .probe samples",
)
def test_session_vm_matches_r4cz(uid: str):
    sess = PROBE / f"{uid}.session.bin"
    binz = PROBE / f"{uid}.binz"
    r4 = PROBE / f"{uid}.r4cz"
    if not (sess.is_file() and binz.is_file() and r4.is_file()):
        pytest.skip(f"missing probe files for {uid}")
    out = decrypt_binz_with_session(binz.read_bytes(), sess.read_bytes())
    assert out == r4.read_bytes()


@pytest.mark.skipif(
    not (PROBE / f"{UIDS[0]}.protection.b64").is_file(),
    reason="no local .probe protection",
)
def test_stream_via_protection_to_osgjs():
    import base64

    uid = UIDS[0]
    raw = (PROBE / f"{uid}.binz").read_bytes()
    prot = base64.b64decode((PROBE / f"{uid}.protection.b64").read_text())
    osgjs = (PROBE / f"{uid}.osgjs").read_bytes()
    r4 = decrypt_binz_to_r4cz(raw, prot)
    assert r4[:4] == b"r4Cz"
    assert inflate_r4cz(r4) == osgjs
