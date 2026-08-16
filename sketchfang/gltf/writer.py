"""Write decoded meshes and resolved materials out as a single .glb."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from ..materials.resolve import ResolvedMaterial, fallback_material, resolve_material
from ..materials.stateset import GeometryBinding
from ..textures.models import TextureAsset
from ..util.io import pad4
from ..util.log import log
from ..util.matrix import IDENTITY_MAT, Z_UP_TO_Y_UP, mat4_multiply
from .constants import (
    GL_FLOAT,
    GL_TRIANGLES,
    GL_UNSIGNED_INT,
    GL_UNSIGNED_SHORT,
    GLB_CHUNK_BIN,
    GLB_CHUNK_JSON,
    GLB_MAGIC,
    GLB_VERSION,
)


def material_to_gltf(mat: ResolvedMaterial, tex_index: dict[str, int]) -> dict:
    """Build one glTF material dict from a ResolvedMaterial + uid→texture index map."""
    transforms = dict(mat.uv_transforms)

    def tex_info(uid: str | None, slot: str) -> dict | None:
        if not uid or uid not in tex_index:
            return None
        info: dict = {"index": tex_index[uid]}
        uv = transforms.get(slot)
        if uv is not None:
            info["extensions"] = {
                "KHR_texture_transform": {
                    "offset": list(uv.offset),
                    "scale": list(uv.scale),
                    "rotation": uv.rotation,
                }
            }
        return info

    pbr: dict = {
        "baseColorFactor": list(mat.base_color_factor),
        "metallicFactor": mat.metallic_factor,
        "roughnessFactor": mat.roughness_factor,
    }
    out: dict = {"name": mat.name or "material", "pbrMetallicRoughness": pbr}

    base = tex_info(mat.base_color_uid, "baseColor")
    if base:
        pbr["baseColorTexture"] = base
    mr = tex_info(mat.metallic_roughness_uid, "metallicRoughness")
    if mr:
        pbr["metallicRoughnessTexture"] = mr
    normal = tex_info(mat.normal_uid, "normal")
    if normal:
        if mat.normal_scale != 1.0:
            normal["scale"] = mat.normal_scale
        out["normalTexture"] = normal
    occlusion = tex_info(mat.occlusion_uid, "occlusion")
    if occlusion:
        if mat.occlusion_strength != 1.0:
            occlusion["strength"] = mat.occlusion_strength
        out["occlusionTexture"] = occlusion
    emissive = tex_info(mat.emissive_uid, "emissive")
    if emissive:
        out["emissiveTexture"] = emissive
        out["emissiveFactor"] = (
            list(mat.emissive_factor) if any(mat.emissive_factor) else [1.0, 1.0, 1.0]
        )
    elif any(mat.emissive_factor):
        out["emissiveFactor"] = list(mat.emissive_factor)

    if mat.clearcoat_factor > 0.0:
        coat: dict = {
            "clearcoatFactor": mat.clearcoat_factor,
            "clearcoatRoughnessFactor": mat.clearcoat_roughness,
        }
        coat_tex = tex_info(mat.clearcoat_uid, "clearcoat")
        if coat_tex:
            coat["clearcoatTexture"] = coat_tex
        out["extensions"] = {"KHR_materials_clearcoat": coat}

    if mat.alpha_mode and mat.alpha_mode != "OPAQUE":
        out["alphaMode"] = mat.alpha_mode
        if mat.alpha_mode == "MASK":
            out["alphaCutoff"] = mat.alpha_cutoff
    if mat.double_sided:
        out["doubleSided"] = True
    return out


def _used_texture_uids(
    meshes: list[dict], assets: dict[str, TextureAsset]
) -> set[str]:
    """Only embed textures referenced by materials (files stay under textures/)."""
    used: set[str] = set()
    for mesh in meshes:
        binding = mesh.get("binding")
        if isinstance(binding, GeometryBinding) and binding.material:
            m = binding.material
            for uid in (
                m.base_color_uid,
                m.normal_uid,
                m.metallic_roughness_uid,
                m.occlusion_uid,
                m.emissive_uid,
                m.clearcoat_uid,
            ):
                if uid and uid in assets:
                    used.add(uid)
    return used


def _extensions_used(materials: list[dict]) -> list[str]:
    used: set[str] = set()
    for material in materials:
        used.update(material.get("extensions") or {})
        coat = (material.get("extensions") or {}).get("KHR_materials_clearcoat", {})
        for info in (
            material.get("pbrMetallicRoughness", {}).get("baseColorTexture"),
            material.get("pbrMetallicRoughness", {}).get("metallicRoughnessTexture"),
            material.get("normalTexture"),
            material.get("occlusionTexture"),
            material.get("emissiveTexture"),
            coat.get("clearcoatTexture"),
        ):
            if isinstance(info, dict):
                used.update(info.get("extensions") or {})
    return sorted(used)


def root_axis_matrix(orientation: list[float] | None = None) -> list[float]:
    """
    Sketchfab OSGJS → glTF axis fix.

    Compose ``Z_UP_TO_Y_UP * orientation`` so the author's orientation (from
    `/options`) is applied in OSG space, then converted to glTF Y-up.
    """
    ori = orientation if orientation is not None else IDENTITY_MAT
    return mat4_multiply(Z_UP_TO_Y_UP, ori)


def write_glb(
    meshes: list[dict],
    assets: dict[str, TextureAsset],
    output_path: Path,
    progress: bool = True,
    *,
    root_matrix: list[float] | None = None,
) -> None:
    gltf: dict = {
        "asset": {"version": "2.0", "generator": "sketchfang"},
        "scene": 0,
        "scenes": [{"nodes": []}],
        "nodes": [],
        "meshes": [],
        "accessors": [],
        "bufferViews": [],
        "buffers": [{"byteLength": 0}],
        "materials": [],
        "textures": [],
        "images": [],
        "samplers": [],
    }
    chunks: list[bytes] = []

    def append_bin(raw: bytes) -> int:
        off = sum(len(c) for c in chunks)
        chunks.append(pad4(raw))
        return off

    def add_buffer_view(raw: bytes) -> int:
        bv_off = append_bin(raw)
        gltf["bufferViews"].append(
            {"buffer": 0, "byteOffset": bv_off, "byteLength": len(raw)}
        )
        return len(gltf["bufferViews"]) - 1

    def add_float_accessor(values: list[float], comps: int, type_name: str) -> int:
        count = len(values) // comps
        raw = struct.pack(f"<{len(values)}f", *values)
        accessor: dict = {
            "bufferView": add_buffer_view(raw),
            "componentType": GL_FLOAT,
            "count": count,
            "type": type_name,
        }
        if comps >= 1:
            accessor["min"] = [min(values[i::comps]) for i in range(comps)]
            accessor["max"] = [max(values[i::comps]) for i in range(comps)]
        gltf["accessors"].append(accessor)
        return len(gltf["accessors"]) - 1

    def add_index_accessor(indices: list[int]) -> int:
        if max(indices, default=0) > 65535:
            raw = struct.pack(f"<{len(indices)}I", *indices)
            ctype = GL_UNSIGNED_INT
        else:
            raw = struct.pack(f"<{len(indices)}H", *indices)
            ctype = GL_UNSIGNED_SHORT
        gltf["accessors"].append(
            {
                "bufferView": add_buffer_view(raw),
                "componentType": ctype,
                "count": len(indices),
                "type": "SCALAR",
            }
        )
        return len(gltf["accessors"]) - 1

    tex_index: dict[str, int] = {}
    used_uids = _used_texture_uids(meshes, assets)
    if used_uids:
        gltf["samplers"].append(
            {"magFilter": 9729, "minFilter": 9987, "wrapS": 10497, "wrapT": 10497}
        )
        for uid in sorted(used_uids):
            asset = assets[uid]
            img = asset.path.read_bytes()
            bv_idx = add_buffer_view(img)
            img_idx = len(gltf["images"])
            gltf["images"].append(
                {"bufferView": bv_idx, "mimeType": asset.mime, "name": asset.name or uid}
            )
            tex_index[uid] = len(gltf["textures"])
            gltf["textures"].append({"source": img_idx, "sampler": 0})

    # Deduplicate materials by binding signature
    mat_cache: dict[str, int] = {}
    default_desc = fallback_material(assets)

    def material_index_for(mesh: dict) -> int:
        binding = mesh.get("binding")
        if isinstance(binding, GeometryBinding) and binding.material is not None:
            desc = resolve_material(binding, assets)
        else:
            desc = default_desc
        if desc.key in mat_cache:
            return mat_cache[desc.key]
        idx = len(gltf["materials"])
        gltf["materials"].append(material_to_gltf(desc, tex_index))
        mat_cache[desc.key] = idx
        return idx

    mesh_node_indices: list[int] = []
    for mi, mesh in enumerate(meshes):
        prim: dict = {
            "attributes": {},
            "mode": GL_TRIANGLES,
            "material": material_index_for(mesh),
        }
        prim["attributes"]["POSITION"] = add_float_accessor(mesh["positions"], 3, "VEC3")
        if mesh.get("normals"):
            prim["attributes"]["NORMAL"] = add_float_accessor(mesh["normals"], 3, "VEC3")
        if mesh.get("uvs"):
            prim["attributes"]["TEXCOORD_0"] = add_float_accessor(mesh["uvs"], 2, "VEC2")
        prim["indices"] = add_index_accessor(mesh["indices"])

        mesh_idx = len(gltf["meshes"])
        gltf["meshes"].append({"primitives": [prim], "name": mesh.get("name") or f"mesh_{mi}"})
        node: dict = {"mesh": mesh_idx, "name": mesh.get("name") or f"mesh_{mi}"}
        matrix = mesh.get("matrix")
        if matrix and matrix != IDENTITY_MAT:
            node["matrix"] = [float(x) for x in matrix]
        node_idx = len(gltf["nodes"])
        gltf["nodes"].append(node)
        mesh_node_indices.append(node_idx)

    # Root converts Sketchfab Z-up (+ optional author orientation) into glTF Y-up.
    axis = root_matrix if root_matrix is not None else root_axis_matrix()
    root_idx = len(gltf["nodes"])
    root: dict = {"name": "SketchfabRoot", "children": mesh_node_indices}
    if axis != IDENTITY_MAT:
        root["matrix"] = [float(x) for x in axis]
    gltf["nodes"].append(root)
    gltf["scenes"][0]["nodes"] = [root_idx]

    # Fix offsets after padding
    off = 0
    for bv in gltf["bufferViews"]:
        bv["byteOffset"] = off
        bl = bv["byteLength"]
        off += bl + ((4 - bl % 4) % 4)

    # Drop empty optional collections
    for key in ("textures", "images", "samplers"):
        if not gltf[key]:
            del gltf[key]

    extensions_used = _extensions_used(gltf["materials"])
    if extensions_used:
        gltf["extensionsUsed"] = extensions_used

    total_bin = b"".join(chunks)
    gltf["buffers"][0]["byteLength"] = len(total_bin)
    json_bytes = pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")
    total_len = 12 + 8 + len(json_bytes) + 8 + len(total_bin)
    with open(output_path, "wb") as f:
        f.write(struct.pack("<III", GLB_MAGIC, GLB_VERSION, total_len))
        f.write(struct.pack("<II", len(json_bytes), GLB_CHUNK_JSON))
        f.write(json_bytes)
        f.write(struct.pack("<II", len(total_bin), GLB_CHUNK_BIN))
        f.write(total_bin)
    if progress:
        log(
            f"[*] Wrote {output_path} ({total_len:,} bytes, "
            f"{len(meshes)} meshes, {len(gltf['materials'])} materials, "
            f"{len(assets)} textures)"
        )
