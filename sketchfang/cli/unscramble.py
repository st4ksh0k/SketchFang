"""`sketchfang-unscramble` — decode one CDN texture with its viewer `pk`."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..textures.unscramble import unscramble_file


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="sketchfang-unscramble",
        description="Unscramble a Sketchfab texture via the viewer pk shader",
    )
    ap.add_argument("image", type=Path)
    ap.add_argument("pk", type=int)
    ap.add_argument("-o", "--output")
    ap.add_argument("--flip-y", action="store_true", help="Apply viewer uY flip")
    ap.add_argument("--flip-x", action="store_true", help="Mirror X (breaks OSG UVs)")
    args = ap.parse_args()

    dest = unscramble_file(
        args.image,
        args.pk,
        args.output,
        flip_y=args.flip_y,
        flip_x=args.flip_x,
    )
    print(dest)


if __name__ == "__main__":
    main()
