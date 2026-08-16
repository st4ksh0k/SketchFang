"""
End-to-end rip: metadata → decrypt → textures → materials → geometry → GLB.

This module only sequences the layers; every step it calls lives in its own
module and can be used on its own.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .api.client import download_bytes
from .api.metadata import fetch_metadata, model_file_url, osgjs_url_of, pick_best_file
from .api.options import fetch_options, orientation_matrix
from .crypto.stream import decrypt_binz
from .gltf.writer import root_axis_matrix, write_glb
from .materials.resolve import prepare_materials
from .materials.stateset import StateSetBinder
from .osgjs.geometry import decode_geometry
from .osgjs.walk import walk_geometries
from .textures.download import extract_textures
from .textures.models import TextureAsset
from .util.log import log
from .util.uid import extract_uid, looks_like_uid


def _safe_name(name: str, fallback: str) -> str:
    return re.sub(r"[^\w\-]+", "_", name).strip("_") or fallback


def fetch_and_decrypt_streams(
    uid: str, *, progress: bool = True
) -> tuple[bytes, bytes, str]:
    """Download and decrypt `file.binz` + `model_file.binz`; also return the model name."""
    meta = fetch_metadata(uid, progress=progress)
    best = pick_best_file(meta)
    osgjs_url = osgjs_url_of(best)
    protection = best.get("p")

    osgjs_raw = download_bytes(osgjs_url, progress=progress, label="file.binz")
    if progress:
        log("[*] Decrypting file.binz ...")
    osgjs_data = decrypt_binz(osgjs_raw, protection, progress=progress)

    model_raw = download_bytes(
        model_file_url(osgjs_url), progress=progress, label="model_file.binz"
    )
    if progress:
        log("[*] Decrypting model_file.binz ...")
    model_bin = decrypt_binz(model_raw, protection, progress=progress)

    return osgjs_data, model_bin, _safe_name(str(meta.get("name", uid)), uid)


def decode_meshes(
    scene: dict,
    bin_map: dict[str, bytes],
    binder: StateSetBinder,
    *,
    progress: bool = True,
) -> list[dict]:
    geoms: list = []
    walk_geometries(scene, geoms, binder)
    if progress:
        log(f"[*] Found {len(geoms)} osg.Geometry node(s), decoding ...")

    meshes: list[dict] = []
    bound = 0
    for i, (geom, world, binding) in enumerate(geoms):
        try:
            mesh = decode_geometry(geom, bin_map, world, binding)
        except Exception as exc:
            if progress and i < 5:
                log(f"[!] Skip geom {geom.get('Name')}: {exc}")
            continue
        if mesh:
            meshes.append(mesh)
            if mesh["binding"] is not None and mesh["binding"].material is not None:
                bound += 1
        if progress and (i % 200 == 0 or i == len(geoms) - 1):
            log(f"[*] Decoded {i + 1}/{len(geoms)} geometries -> {len(meshes)} meshes")

    if not meshes:
        raise RuntimeError("No triangle meshes decoded from OSGJS")
    if progress:
        log(f"[*] Materials resolved on {bound}/{len(meshes)} mesh(es)")
    return meshes


def rip_model(
    url_or_uid: str,
    output_dir: Path | None = None,
    *,
    no_textures: bool = False,
    progress: bool = True,
    # Offline overrides for testing:
    osgjs_path: Path | None = None,
    model_bin_path: Path | None = None,
) -> Path:
    offline = osgjs_path is not None
    uid = extract_uid(url_or_uid) if (not offline or looks_like_uid(url_or_uid)) else "local"

    if not offline:
        osgjs_data, model_bin, model_name = fetch_and_decrypt_streams(uid, progress=progress)
        out_dir = output_dir or Path(f"./{model_name}")
    else:
        if model_bin_path is None:
            raise ValueError("model_bin_path required with osgjs_path")
        model_name = "local"
        out_dir = output_dir or Path("./local_osgjs")
        osgjs_data = Path(osgjs_path).read_bytes()
        model_bin = Path(model_bin_path).read_bytes()
        if progress:
            log(f"[*] Offline OSGJS {len(osgjs_data):,} B, model {len(model_bin):,} B")
    out_dir.mkdir(parents=True, exist_ok=True)

    scene = json.loads(osgjs_data.decode("utf-8"))
    bin_map = {"model_file.binz": model_bin, "model_file.bin": model_bin}

    # Textures first so prepare_materials can bind them into slots
    assets: dict[str, TextureAsset] = {}
    if not no_textures and not offline:
        try:
            assets = extract_textures(uid, out_dir, progress=progress)
        except Exception as exc:
            if progress:
                log(f"[!] Texture download failed: {exc}")

    options: dict | None = None
    if not offline:
        try:
            options = fetch_options(uid)
        except Exception as exc:
            if progress:
                log(f"[!] Material options unavailable ({exc}); factors only")

    registry, by_name = prepare_materials(
        scene,
        assets,
        options=options,
        progress=progress,
        output_dir=out_dir,
    )

    meshes = decode_meshes(
        scene, bin_map, StateSetBinder(registry, by_name), progress=progress
    )

    # OSGJS is Z-up; glTF is Y-up. Also honour the author's orientation matrix.
    axis = root_axis_matrix(orientation_matrix(options))
    if progress:
        log("[*] Applying Sketchfab Z-up → glTF Y-up root transform")

    out_path = out_dir / f"{model_name}.glb"
    write_glb(meshes, assets, out_path, progress=progress, root_matrix=axis)
    return out_path
