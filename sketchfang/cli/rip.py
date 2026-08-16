"""`sketchfang` — convert a Sketchfab OSGJS/BINZ stream to GLB."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..pipeline import rip_model
from ..util.log import enable_line_buffering


def main() -> None:
    enable_line_buffering()

    parser = argparse.ArgumentParser(
        prog="sketchfang",
        description=(
            "SketchFang (educational): convert a Sketchfab OSGJS/BINZ stream to GLB. "
            "Use only on models you own or have permission to study."
        ),
    )
    parser.add_argument("url_or_uid", help="Sketchfab model URL or 32-char UID")
    parser.add_argument("-o", "--output-dir", default=None, help="Output directory")
    parser.add_argument("--no-textures", action="store_true")
    parser.add_argument("-q", "--quiet", action="store_true")
    parser.add_argument("--osgjs", help="Offline: path to decrypted OSGJS (skip download)")
    parser.add_argument("--model-bin", help="Offline: path to decrypted model_file.bin")
    args = parser.parse_args()

    out = rip_model(
        args.url_or_uid,
        Path(args.output_dir) if args.output_dir else None,
        no_textures=args.no_textures,
        progress=not args.quiet,
        osgjs_path=Path(args.osgjs) if args.osgjs else None,
        model_bin_path=Path(args.model_bin) if args.model_bin else None,
    )
    print(f"Done.  Output: {out}")


if __name__ == "__main__":
    main()
