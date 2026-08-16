"""`sketchfang-decrypt` — BINZ → OSGJS, from a UID or a local file."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..api.client import download_bytes
from ..api.metadata import fetch_metadata, osgjs_url_of, pick_best_file
from ..crypto.stream import decrypt_binz
from ..util.log import enable_line_buffering, log
from ..util.uid import extract_uid


def fetch_and_decrypt(uid: str, *, progress: bool = True) -> bytes:
    meta = fetch_metadata(uid, progress=progress)
    best = pick_best_file(meta)
    url = osgjs_url_of(best)
    protection = best.get("p")
    if not protection:
        raise RuntimeError("No protection key in metadata")
    entry = protection[0] if isinstance(protection, list) else protection
    if not entry or not entry.get("b"):
        raise RuntimeError("No protection key in metadata")

    raw = download_bytes(url, progress=progress, label="file.binz")
    return decrypt_binz(raw, protection, progress=progress)


def main() -> None:
    enable_line_buffering()

    parser = argparse.ArgumentParser(
        prog="sketchfang-decrypt",
        description="Decrypt Sketchfab BINZ to OSGJS (pure Python)",
    )
    parser.add_argument("url_or_uid", nargs="?", help="Model URL or 32-char UID")
    parser.add_argument("--raw", help="Local .binz file instead of fetching")
    parser.add_argument("--key", help="Protection key base64 (files[].p[].b)")
    parser.add_argument("-o", "--output", default="decrypted.osgjs")
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress progress (errors still go to stderr)",
    )
    args = parser.parse_args()
    progress = not args.quiet

    if args.raw:
        if not args.key:
            log("--key is required with --raw")
            sys.exit(1)
        encrypted = Path(args.raw).read_bytes()
        if progress:
            log(f"[*] Loaded {len(encrypted):,} bytes from {args.raw}")
        out = decrypt_binz(encrypted, {"b": args.key}, progress=progress)
    else:
        if not args.url_or_uid:
            parser.print_help()
            sys.exit(1)
        uid = extract_uid(args.url_or_uid)
        if progress:
            log(f"[*] UID: {uid}")
        out = fetch_and_decrypt(uid, progress=progress)

    dest = Path(args.output)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(out)
    log(f"[*] Wrote {len(out):,} bytes -> {dest}")
    log(f"[*] Magic: {out[:4]!r}")


if __name__ == "__main__":
    main()
