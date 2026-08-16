#!/usr/bin/env python3
"""
BINZ / protection characterization probe (educational).

Classifies framing of protection.b vs file.binz and runs the pure-Python
stream decrypt to dump r4Cz / OSGJS sizes.
"""

from __future__ import annotations

import argparse
import base64
import math
import struct
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sketchfang.api.client import download_bytes  # noqa: E402
from sketchfang.api.metadata import fetch_metadata, osgjs_url_of, pick_best_file  # noqa: E402
from sketchfang.crypto.protection import (  # noqa: E402
    STATIC_KEY_HEX,
    reveal_zstd_frame,
    static_key_schedule,
    unwrap_protection,
)
from sketchfang.crypto.r4cz import inflate_r4cz, parse_r4cz  # noqa: E402
from sketchfang.crypto.stream import decrypt_binz_to_r4cz  # noqa: E402
from sketchfang.util.uid import extract_uid  # noqa: E402


def hx(b: bytes, n: int = 32) -> str:
    return b[:n].hex() + ("…" if len(b) > n else "")


def classify(data: bytes, label: str) -> None:
    print(f"\n=== {label} ({len(data):,} bytes) ===")
    if not data:
        print("  <empty>")
        return
    print(f"  head32: {hx(data)}")
    magic32 = struct.unpack_from("<I", data, 0)[0] if len(data) >= 4 else None
    if magic32 is not None:
        print(f"  u32le[0]: 0x{magic32:08x}")
    tags = []
    if data[:4] == b"\x28\xb5\x2f\xfd":
        tags.append("ZSTD_MAGIC")
    if len(data) >= 4 and magic32 is not None and (magic32 & 0xFFFFFFF0) == 0x184D2A50:
        tags.append("ZSTD_SKIPPABLE_FAMILY")
    if data[:4] == b"\x04\x22\x4d\x18":
        tags.append("LZ4_FRAME")
    if data[:2] == b"\x1f\x8b":
        tags.append("GZIP")
    if data[:4] == b"r4Cz":
        tags.append("R4CZ")
    if data[:1] in (b"{", b"["):
        tags.append("JSON_TEXT")
    c = Counter(data[:4096])
    n = min(len(data), 4096)
    ent = -sum((v / n) * math.log2(v / n) for v in c.values()) if n else 0
    print(f"  entropy@4k: {ent:.3f} bits/byte")
    print(f"  tags: {tags or ['unknown']}")


def probe_decrypt(raw: bytes, protection_b64: str) -> None:
    prot = base64.b64decode(
        protection_b64.replace("\n", "").replace("\r", "").replace(" ", "")
    )
    schedule = static_key_schedule()
    mixed = reveal_zstd_frame(prot)
    session = unwrap_protection(prot)

    classify(prot, "protection.b decoded")
    print(f"\n=== static key schedule (24 B from {STATIC_KEY_HEX[:40]}) ===")
    print(f"  schedule: {schedule.hex()}")
    classify(mixed, "protection after key-mix (Zstd frame)")
    classify(session, "session (zstd payload)")
    classify(raw, "file.binz")

    r4 = decrypt_binz_to_r4cz(raw, prot)
    c = parse_r4cz(r4)
    osgjs = inflate_r4cz(r4)
    classify(r4, "r4Cz (after stream cipher)")
    print(
        f"  r4Cz: ver={c.version} frames={c.nframes} "
        f"unc={c.uncompressed_size} hdr={c.header_size} ends={c.frame_ends}"
    )
    classify(osgjs, "OSGJS (inflated)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("uid_or_url", nargs="?", help="Sketchfab UID/URL")
    ap.add_argument("--raw", type=Path, help="Local .binz")
    ap.add_argument("--key", help="protection.b base64 (with --raw)")
    ap.add_argument("--schedule-only", action="store_true")
    args = ap.parse_args()

    if args.schedule_only:
        print(static_key_schedule().hex())
        return 0

    if args.raw:
        if not args.key:
            ap.error("--key required with --raw")
        probe_decrypt(args.raw.read_bytes(), args.key)
        return 0

    if not args.uid_or_url:
        ap.error("uid_or_url or --raw/--key required")

    uid = extract_uid(args.uid_or_url)
    meta = fetch_metadata(uid)
    best = pick_best_file(meta)
    prot = (best.get("p") or [None])[0]
    if not prot or not prot.get("b"):
        raise SystemExit("No protection.b in metadata")
    print(f"protection entry keys: {sorted(prot.keys())}")
    url = osgjs_url_of(best)
    print(f"osgjsUrl: {url}")
    raw = download_bytes(url, label="file.binz")
    out_dir = ROOT / ".probe"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{uid}.binz").write_bytes(raw)
    (out_dir / f"{uid}.protection.b64").write_text(prot["b"])
    print(f"saved under {out_dir}/")
    probe_decrypt(raw, prot["b"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
