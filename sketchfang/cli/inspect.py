"""
`sketchfang-inspect` — print the material/texture table of a GLB.

Used to confirm that every material a model defines actually came out of the
rip with its textures attached.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from ..gltf.reader import read_gltf_json

SLOTS = (
    ("baseColor", lambda m: m.get("pbrMetallicRoughness", {}).get("baseColorTexture")),
    ("metalRough", lambda m: m.get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture")),
    ("normal", lambda m: m.get("normalTexture")),
    ("occlusion", lambda m: m.get("occlusionTexture")),
    ("emissive", lambda m: m.get("emissiveTexture")),
)


def report(path: Path) -> int:
    """Print one GLB's material table; returns the untextured material count."""
    gltf = read_gltf_json(path)
    images = gltf.get("images", [])
    textures = gltf.get("textures", [])
    materials = gltf.get("materials", [])

    def image_name(info: dict | None) -> str | None:
        if not isinstance(info, dict):
            return None
        src = textures[info["index"]].get("source")
        return images[src].get("name", f"image_{src}") if src is not None else None

    print(f"{path}  —  {len(materials)} materials, {len(images)} embedded images")
    untextured = 0
    for mat in materials:
        pbr = mat.get("pbrMetallicRoughness", {})
        bound = [
            f"{slot}={image_name(get(mat))}"
            for slot, get in SLOTS
            if image_name(get(mat))
        ]
        if not bound:
            untextured += 1
        flags = []
        if pbr.get("metallicFactor"):
            flags.append(f"metal={pbr['metallicFactor']:.2g}")
        if mat.get("alphaMode"):
            flags.append(mat["alphaMode"].lower())
        if any(mat.get("emissiveFactor") or []):
            flags.append("emits")
        suffix = f"  [{', '.join(flags)}]" if flags else ""
        print(f"  {mat.get('name', '?'):<28} {', '.join(bound) or 'untextured'}{suffix}")

    print(f"  -> {len(materials) - untextured}/{len(materials)} textured")
    return untextured


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="sketchfang-inspect", description="Print the material/texture table of a GLB"
    )
    ap.add_argument("glb", nargs="+", type=Path)
    args = ap.parse_args()
    for i, path in enumerate(args.glb):
        if i:
            print()
        report(path)


if __name__ == "__main__":
    main()
