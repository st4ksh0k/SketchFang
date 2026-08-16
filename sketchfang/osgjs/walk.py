"""
Scene graph walk: flatten OSGJS nodes into geometries with world matrices.

Material joining is delegated to a binder so this layer stays free of material
knowledge; ``materials.stateset.StateSetBinder`` is the real implementation.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .transforms import IDENTITY_MAT, mat4_multiply, matrix_from_transform


@runtime_checkable
class GeometryBinder(Protocol):
    """Resolves whatever material state a node contributes while walking."""

    def for_node(self, node: dict, inherited: Any) -> Any: ...

    def for_geometry(self, geom: dict, inherited: Any) -> Any: ...


class NullBinder:
    """Walk the scene without resolving materials."""

    def for_node(self, node: dict, inherited: Any) -> Any:
        return inherited

    def for_geometry(self, geom: dict, inherited: Any) -> Any:
        return inherited


NULL_BINDER = NullBinder()

WalkedGeometry = tuple[dict, list[float], Any]


def walk_geometries(
    node: Any,
    out: list[WalkedGeometry],
    binder: GeometryBinder | None = None,
    parent_matrix: list[float] | None = None,
    parent_binding: Any = None,
) -> None:
    """Collect `(geometry, world_matrix, binding)` for every osg.Geometry."""
    if binder is None:
        binder = NULL_BINDER
    if parent_matrix is None:
        parent_matrix = IDENTITY_MAT[:]

    if isinstance(node, dict):
        binding = binder.for_node(node, parent_binding)
        if "osg.MatrixTransform" in node:
            mt = node["osg.MatrixTransform"]
            local = matrix_from_transform(mt)
            if local is None:
                return  # hidden animated subtree
            world = mat4_multiply(parent_matrix, local)
            binding = binder.for_node(mt, binding)
            for child in mt.get("Children") or []:
                walk_geometries(child, out, binder, world, binding)
            return
        if "osg.Geometry" in node:
            geom = node["osg.Geometry"]
            out.append((geom, parent_matrix[:], binder.for_geometry(geom, binding)))
            return
        # Generic nodes: keep walking children / nested wrappers
        if "Children" in node and isinstance(node["Children"], list):
            for child in node["Children"]:
                walk_geometries(child, out, binder, parent_matrix, binding)
            return
        for key in ("osg.Node", "osg.MatrixTransform", "Node", "MatrixTransform"):
            if key in node:
                walk_geometries(node[key], out, binder, parent_matrix, binding)
                return
        for v in node.values():
            walk_geometries(v, out, binder, parent_matrix, binding)
    elif isinstance(node, list):
        for v in node:
            walk_geometries(v, out, binder, parent_matrix, parent_binding)
