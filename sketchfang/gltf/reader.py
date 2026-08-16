"""Read-only GLB access, used to verify a rip and debug UV / transform issues."""

from __future__ import annotations

import json
import struct
from pathlib import Path

from ..util.matrix import (
    IDENTITY_MAT,
    mat4_from_quat,
    mat4_from_scale,
    mat4_from_translation,
    mat4_multiply,
    transform_point,
)
from .constants import COMPONENT, GLB_CHUNK_BIN, GLB_CHUNK_JSON, GLB_MAGIC, NUM_COMPONENTS

__all__ = ["Glb", "node_matrix", "read_gltf_json", "transform_point"]


def _chunks(data: bytes):
    if struct.unpack_from("<I", data, 0)[0] != GLB_MAGIC:
        raise ValueError("not a GLB")
    off = 12
    while off < len(data):
        clen, ctype = struct.unpack_from("<II", data, off)
        yield ctype, data[off + 8 : off + 8 + clen]
        off += 8 + clen + ((4 - clen % 4) % 4)


def read_gltf_json(path: Path) -> dict:
    for ctype, chunk in _chunks(Path(path).read_bytes()):
        if ctype == GLB_CHUNK_JSON:
            return json.loads(chunk.decode("utf-8"))
    raise ValueError(f"{path}: no JSON chunk")


def node_matrix(node: dict) -> list[float]:
    """glTF node TRS (or explicit matrix) → column-major 4x4."""
    if "matrix" in node:
        return [float(x) for x in node["matrix"]]
    rotation = node.get("rotation")
    scale = node.get("scale")
    translation = node.get("translation")
    m = mat4_from_quat(rotation) if rotation else IDENTITY_MAT[:]
    if scale:
        m = mat4_multiply(m, mat4_from_scale(scale))
    if translation:
        m = mat4_multiply(mat4_from_translation(translation), m)
    return m


class Glb:
    """A parsed GLB: JSON chunk, BIN chunk, accessors, and world matrices."""

    def __init__(self, path: Path | str):
        self.json: dict = {}
        self.bin = b""
        self._world: dict[int, list[float]] | None = None
        for ctype, chunk in _chunks(Path(path).read_bytes()):
            if ctype == GLB_CHUNK_JSON:
                self.json = json.loads(chunk.decode("utf-8"))
            elif ctype == GLB_CHUNK_BIN:
                self.bin = chunk

    def accessor(self, index: int) -> list:
        acc = self.json["accessors"][index]
        fmt, size = COMPONENT[acc["componentType"]]
        n = NUM_COMPONENTS[acc["type"]]
        view = self.json["bufferViews"][acc["bufferView"]]
        base = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or size * n
        out: list = []
        for i in range(acc["count"]):
            out.extend(struct.unpack_from("<" + fmt * n, self.bin, base + i * stride))
        return out

    def world_matrices(self) -> dict[int, list[float]]:
        """World matrix per node index, resolved from the scene roots."""
        if self._world is not None:
            return self._world
        nodes = self.json.get("nodes", [])
        world: dict[int, list[float]] = {}

        def walk(i: int, parent: list[float]) -> None:
            here = mat4_multiply(parent, node_matrix(nodes[i]))
            world[i] = here
            for c in nodes[i].get("children", []):
                walk(c, here)

        for scene in self.json.get("scenes", []):
            for root in scene.get("nodes", []):
                walk(root, IDENTITY_MAT)
        self._world = world
        return world
