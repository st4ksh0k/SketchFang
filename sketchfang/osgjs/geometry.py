"""
One `osg.Geometry` → a mesh dict consumed by ``gltf.writer``.

Mesh contract:
    {"name", "positions", "normals", "uvs", "indices", "matrix", "binding"}
`binding` is passed through untouched from the scene walk.
"""

from __future__ import annotations

from typing import Any

from .buffers import parse_userdata, read_array_buffer
from .codecs import (
    ATTR_NORMAL,
    ATTR_TRIANGLE,
    TRI_DELTA,
    TRI_IMPLICIT,
    TRI_WATERMARK,
    VTX_BBOX,
    VTX_PREDICT,
    delta_decode,
    dequantize,
    implicit_expand,
    predict_vertices,
    strip_to_triangles,
    unpack_normals,
    watermark_decode_u16,
)
from .transforms import IDENTITY_MAT, mat4_is_degenerate


def decode_primitive_indices(
    geom: dict,
    ud: dict,
    bin_map: dict[str, bytes],
) -> tuple[list[list[int]], list[int] | None]:
    """
    Return (triangle_index_groups, predict_indices).

    predict_indices is the decoded index buffer from the last TRIANGLE_STRIP
    (viewer uses that for parallelogram vertex prediction).
    """
    attrs = int(ud.get("attributes") or 0)
    tri_mode = int(ud.get("triangle_mode") or 0)
    wm_state = [0]
    triangles: list[list[int]] = []
    predict_indices: list[int] | None = None

    for prim in geom.get("PrimitiveSetList") or []:
        if not isinstance(prim, dict):
            continue
        for _kind, pv in prim.items():
            if not isinstance(pv, dict):
                continue
            mode = pv.get("Mode")
            if mode not in ("TRIANGLES", "TRIANGLE_STRIP"):
                continue
            indices = pv.get("Indices") or {}
            arr = indices.get("Array") or {}
            if not arr:
                continue
            type_name = next(iter(arr))
            vals = [int(x) for x in read_array_buffer(arr, indices.get("ItemSize", 1), bin_map)]

            # Promote Uint8 → Uint16 like the viewer
            if type_name == "Uint8Array":
                vals = [v & 0xFFFF for v in vals]

            is_strip = mode == "TRIANGLE_STRIP"
            use_compressed = (attrs & ATTR_TRIANGLE) != 0 and (
                is_strip or mode == "TRIANGLES"
            )

            if not use_compressed:
                if is_strip:
                    predict_indices = vals
                    triangles.append(strip_to_triangles(vals))
                else:
                    triangles.append(vals)
                continue

            b = 0
            out = vals
            if (tri_mode & TRI_IMPLICIT) and is_strip:
                b = 3 + vals[1]
                out = [0] * vals[0]
            if tri_mode & TRI_DELTA:
                delta_decode(vals, b)
            if (tri_mode & TRI_IMPLICIT) and is_strip:
                out = implicit_expand(vals, vals[0], b, bool(tri_mode & TRI_WATERMARK))
            else:
                out = list(vals)
            if tri_mode & TRI_WATERMARK:
                watermark_decode_u16(out, wm_state)

            # Implicit/delta/watermark recover the strip (or triangle) index
            # buffer — mode stays TRIANGLE_STRIP. Expand strips here for GLB.
            if is_strip:
                predict_indices = out
                triangles.append(strip_to_triangles(out))
            else:
                triangles.append(out)

    return triangles, predict_indices


def decode_vertex_attr(
    geom: dict,
    ud: dict,
    bin_map: dict[str, bytes],
    pred_indices: list[int] | None,
) -> list[float]:
    va = geom["VertexAttributeList"]["Vertex"]
    arr = va["Array"]
    item = int(va.get("ItemSize") or 3)
    vals = [int(x) for x in read_array_buffer(arr, item, bin_map)]
    vm = int(ud.get("vertex_mode") or 0)
    if (vm & VTX_PREDICT) and pred_indices is not None:
        predict_vertices(vals, item, pred_indices)
    if (vm & VTX_BBOX) and "vtx_bbl_x" in ud:
        bbl = [float(ud["vtx_bbl_x"]), float(ud["vtx_bbl_y"]), float(ud.get("vtx_bbl_z", 0.0))]
        step = [float(ud["vtx_h_x"]), float(ud["vtx_h_y"]), float(ud.get("vtx_h_z", 1.0))]
        return dequantize(vals, item, bbl, step)
    return [float(x) for x in vals]


def decode_texcoord(
    geom: dict,
    name: str,
    ud: dict,
    bin_map: dict[str, bytes],
    pred_indices: list[int] | None,
) -> list[float]:
    va = geom["VertexAttributeList"][name]
    arr = va["Array"]
    item = int(va.get("ItemSize") or 2)
    vals = [int(x) if not isinstance(x, float) else x for x in read_array_buffer(arr, item, bin_map)]
    # If already floats (Float32Array raw), return as-is
    type_name = next(iter(arr))
    info = arr[type_name]
    if type_name == "Float32Array" and info.get("Encoding") != "varint":
        return [float(x) for x in vals]

    suffix = name[8:] if name.startswith("TexCoord") else "0"
    mode_key = f"uv_{suffix}_mode"
    mode = int(ud[mode_key]) if mode_key in ud else int(ud.get("vertex_mode") or 0)
    int_vals = [int(x) for x in vals]
    if (mode & VTX_PREDICT) and pred_indices is not None:
        predict_vertices(int_vals, item, pred_indices)
    prefix = f"uv_{suffix}_"
    if (mode & VTX_BBOX) and f"{prefix}bbl_x" in ud:
        bbl = [float(ud[f"{prefix}bbl_x"]), float(ud[f"{prefix}bbl_y"])]
        step = [float(ud[f"{prefix}h_x"]), float(ud[f"{prefix}h_y"])]
        return dequantize(int_vals, item, bbl, step)
    return [float(x) for x in int_vals]


def decode_geometry(
    geom: dict,
    bin_map: dict[str, bytes],
    world_matrix: list[float] | None = None,
    binding: Any = None,
) -> dict | None:
    """Decode one osg.Geometry into positions/normals/uvs/indices, or None if empty."""
    ud = parse_userdata(geom)
    # Sketchfab emits a parallel wireframe batch — skip for solid GLB
    if ud.get("wireframe"):
        return None
    attrs = int(ud.get("attributes") or 0)
    index_groups, pred = decode_primitive_indices(geom, ud, bin_map)
    if not index_groups:
        return None

    positions = decode_vertex_attr(geom, ud, bin_map, pred)

    normals: list[float] | None = None
    valist = geom.get("VertexAttributeList") or {}
    if "Normal" in valist and (attrs & ATTR_NORMAL):
        narr = valist["Normal"]
        packed = [int(x) for x in read_array_buffer(narr["Array"], narr.get("ItemSize", 2), bin_map)]
        normals = unpack_normals(
            packed,
            float(ud.get("epsilon") or 0.25),
            int(ud.get("nphi") or 720),
        )

    uvs: list[float] | None = None
    for key in valist:
        if key.startswith("TexCoord"):
            uvs = decode_texcoord(geom, key, ud, bin_map, pred)
            break

    # Merge all triangle groups; drop out-of-range indices
    nverts = len(positions) // 3
    indices: list[int] = []
    for group in index_groups:
        for i in range(0, len(group) - 2, 3):
            a, b, c = group[i], group[i + 1], group[i + 2]
            if a < nverts and b < nverts and c < nverts and a != b and b != c and a != c:
                indices.extend((a, b, c))

    if not indices:
        return None

    matrix = world_matrix[:] if world_matrix is not None else IDENTITY_MAT[:]
    # Skip fully collapsed transforms
    if mat4_is_degenerate(matrix):
        return None

    material = getattr(binding, "material", None)
    name = geom.get("Name") or getattr(material, "name", None) or "mesh"

    return {
        "name": name,
        "positions": positions,
        "normals": normals,
        "uvs": uvs,
        "indices": indices,
        "matrix": matrix,
        "binding": binding,
    }
