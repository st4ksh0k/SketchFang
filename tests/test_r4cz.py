"""r4Cz container parse + Zstd inflate (no WASM)."""

from __future__ import annotations

from pathlib import Path

import pytest

from sketchfang.crypto.r4cz import inflate_r4cz, parse_r4cz

PROBE = Path(__file__).resolve().parents[1] / ".probe"
UID = "e3c3072cab4b4ef2ba8bc796f588d1ef"


@pytest.mark.skipif(
    not (PROBE / f"{UID}.r4cz").is_file(),
    reason="no local .probe r4cz; run scripts/binz_probe.py + decrypt dump first",
)
def test_inflate_matches_osgjs():
    r4 = (PROBE / f"{UID}.r4cz").read_bytes()
    osgjs = (PROBE / f"{UID}.osgjs").read_bytes()
    c = parse_r4cz(r4)
    assert c.version == 1
    assert c.nframes >= 1
    assert c.frame_ends[-1] <= len(r4)
    assert inflate_r4cz(r4) == osgjs


def test_parse_rejects_garbage():
    with pytest.raises(ValueError):
        parse_r4cz(b"not-r4cz-header!!!!!!!!!!!!")
