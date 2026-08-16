#!/usr/bin/env python3
"""
Watch Sketchfab's viewer static key; patch protection.py when it rotates.

Bundles are scanned in memory and discarded. Typical use:

    python3 scripts/watch_static_key.py              # one-shot + commit
    python3 scripts/watch_static_key.py --check-only
    python3 scripts/watch_static_key.py --interval 21600

macOS launchd: see scripts/launchd/com.sketchfang.watch-static-key.plist
"""

from __future__ import annotations

import argparse
import base64
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sketchfang.api.metadata import fetch_metadata, pick_best_file  # noqa: E402
from sketchfang.crypto import protection as prot  # noqa: E402
from sketchfang.crypto.key_watch import (  # noqa: E402
    DEFAULT_PROBE_UID,
    discover_static_key,
    ensure_static_key,
    patch_protection_py,
    validate_static_key,
)
from sketchfang.util.log import log  # noqa: E402
from sketchfang.util.uid import extract_uid  # noqa: E402

PROTECTION_PY = ROOT / "sketchfang" / "crypto" / "protection.py"


def _load_protection_bytes(args: argparse.Namespace) -> bytes | None:
    if args.protection:
        b64 = Path(args.protection).read_text(encoding="utf-8").strip()
        return base64.b64decode(
            b64.replace("\n", "").replace("\r", "").replace(" ", "")
        )
    if args.skip_validate:
        return None
    uid = extract_uid(args.uid)
    meta = fetch_metadata(uid, progress=True)
    best = pick_best_file(meta)
    entry = (best.get("p") or [None])[0]
    if not entry or not entry.get("b"):
        raise RuntimeError(f"no protection.b in metadata for {uid}")
    return base64.b64decode(
        entry["b"].replace("\n", "").replace("\r", "").replace(" ", "")
    )


def _git(args: list[str]) -> None:
    subprocess.run(["git", *args], cwd=ROOT, check=True)


def _commit_and_maybe_push(*, push: bool) -> None:
    _git(["add", str(PROTECTION_PY.relative_to(ROOT))])
    status = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
    )
    if status.returncode == 0:
        log("[*] Nothing to commit")
        return
    msg = f"chore: rotate Sketchfab viewer static key to {prot.STATIC_KEY_HEX}"
    _git(["commit", "-m", msg])
    log(f"[*] Committed: {msg}")
    if push:
        _git(["push"])
        log("[*] Pushed to origin")


def run_once(args: argparse.Namespace) -> int:
    uid = extract_uid(args.uid)
    try:
        protection = _load_protection_bytes(args)
    except Exception as exc:
        log(f"[!] Failed to load protection blob: {exc}")
        return 1

    try:
        if protection is not None:
            # Prefer validate-first path (may no-op without network).
            if validate_static_key(prot.STATIC_KEY_HEX, protection):
                live = prot.STATIC_KEY_HEX
                log(f"[*] Current key still valid: {live}")
            else:
                live = ensure_static_key(
                    protection,
                    uid=uid,
                    auto_refresh=True,
                    patch_file=False,
                    progress=True,
                )
        else:
            live = discover_static_key(uid, progress=True)
    except Exception as exc:
        log(f"[!] Discovery failed: {exc}")
        return 1

    if live == prot.STATIC_KEY_HEX and live in prot.KNOWN_STATIC_KEY_HEX:
        # ensure_static_key may have registered already; compare file too.
        file_text = PROTECTION_PY.read_text(encoding="utf-8")
        if f'STATIC_KEY_HEX = "{live}"' in file_text:
            log(f"[*] Repo key unchanged: {live}")
            return 0

    if args.check_only:
        log(f"[*] Live key {live} (repo has {prot.STATIC_KEY_HEX}); check-only")
        return 0

    try:
        register = live != prot.STATIC_KEY_HEX
        if register:
            prot.register_static_key(live)
        changed = patch_protection_py(live, path=PROTECTION_PY)
    except Exception as exc:
        log(f"[!] Patch failed: {exc}")
        return 2

    if not changed:
        log(f"[*] protection.py already at {live}")
        return 0

    log(f"[*] Patched protection.py → {live}")
    if args.commit:
        try:
            _commit_and_maybe_push(push=args.push)
        except subprocess.CalledProcessError as exc:
            log(f"[!] git failed: {exc}")
            return 2
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--uid",
        default=DEFAULT_PROBE_UID,
        help="Model UID/URL whose embed lists viewer scripts",
    )
    ap.add_argument(
        "--protection",
        type=Path,
        help="Local .protection.b64 for validation (else fetch metadata)",
    )
    ap.add_argument(
        "--skip-validate",
        action="store_true",
        help="Accept first webpack candidate without protection.b check",
    )
    ap.add_argument(
        "--check-only",
        action="store_true",
        help="Report only; do not patch or commit",
    )
    ap.add_argument(
        "--commit",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="git commit protection.py when it changes (default: on)",
    )
    ap.add_argument(
        "--push",
        action="store_true",
        help="git push after a successful commit",
    )
    ap.add_argument(
        "--interval",
        type=int,
        default=0,
        metavar="SEC",
        help="Repeat every SEC seconds (0 = one-shot)",
    )
    args = ap.parse_args()

    if args.interval > 0:
        while True:
            code = run_once(args)
            if code not in (0,):
                log(f"[!] watch iteration exited {code}; sleeping anyway")
            time.sleep(args.interval)
    return run_once(args)


if __name__ == "__main__":
    raise SystemExit(main())
