"""Offline helpers for viewer static-key discovery / patching."""

from __future__ import annotations

from sketchfang.crypto.key_watch import extract_key_candidates, patch_protection_py
from sketchfang.crypto.protection import STATIC_KEY_HEX, reveal_zstd_frame


def test_extract_key_candidates_prefers_exports():
    js = (
        'C04p:t=>{"use strict";t.exports="7d61ef7c7530c12cf080fafd05e603d1aa3a92c6\\n"},'
        'other:"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\\n"'
    )
    keys = extract_key_candidates(js)
    assert keys[0] == "7d61ef7c7530c12cf080fafd05e603d1aa3a92c6"
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in keys


def test_patch_protection_py_roundtrip(tmp_path):
    src = tmp_path / "protection.py"
    src.write_text(
        'STATIC_KEY_HEX = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"\n'
        "\n"
        "KNOWN_STATIC_KEY_HEX: tuple[str, ...] = (\n"
        "    STATIC_KEY_HEX,\n"
        '    "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",\n'
        ")\n",
        encoding="utf-8",
    )
    new = "cccccccccccccccccccccccccccccccccccccccc"
    assert patch_protection_py(new, path=src) is True
    text = src.read_text(encoding="utf-8")
    assert f'STATIC_KEY_HEX = "{new}"' in text
    assert "    STATIC_KEY_HEX," in text
    assert "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" in text
    assert "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb" in text
    assert patch_protection_py(new, path=src) is False


def test_current_static_key_schedule_matches_module():
    # Smoke: schedule from STATIC_KEY_HEX is what unwrap expects to use.
    s = reveal_zstd_frame(bytes(24), static_hex=STATIC_KEY_HEX)
    assert len(s) == 24
