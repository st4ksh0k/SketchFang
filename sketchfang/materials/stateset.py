"""
The OSGJS side of the material join.

A StateSet's UserData `UniqueID` equals the server material's `stateSetID`, so
binding geometry to a material is an exact lookup — no filename inspection
anywhere. ``StateSetBinder`` is what the scene walk calls.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any

from .sketchfab import UVTransform


@dataclass
class MaterialDef:
    """One Sketchfab/OSGJS material (StateSet + optional texture slots)."""

    stateset_uid: int
    name: str
    # StateSet UserData `UniqueID` — equals `stateSetID` in the options API and
    # is the only reliable join between OSGJS geometry and a server material.
    material_slot_id: int | None = None
    base_color_factor: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    metallic_factor: float = 0.0
    roughness_factor: float = 0.6
    emissive_factor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    double_sided: bool = False
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    normal_scale: float = 1.0
    occlusion_strength: float = 1.0
    # Filled by materials.resolve from the server channel table:
    base_color_uid: str | None = None
    normal_uid: str | None = None
    metallic_uid: str | None = None
    roughness_uid: str | None = None
    metallic_roughness_uid: str | None = None  # packed G=rough, B=metal
    occlusion_uid: str | None = None
    emissive_uid: str | None = None
    clearcoat_uid: str | None = None
    clearcoat_factor: float = 0.0
    clearcoat_roughness: float = 0.0
    uv_transforms: dict[str, UVTransform] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return "|".join(
            [
                str(self.stateset_uid),
                self.base_color_uid or "-",
                self.normal_uid or "-",
                self.metallic_roughness_uid or "-",
                self.occlusion_uid or "-",
                self.emissive_uid or "-",
                f"{self.metallic_factor:.4f}",
                f"{self.roughness_factor:.4f}",
                self.alpha_mode,
                ",".join(f"{c:.4f}" for c in self.base_color_factor),
            ]
        )


@dataclass
class GeometryBinding:
    """Resolved material for one geometry after StateSet UniqueID lookup."""

    stateset_uid: int | None = None
    material: MaterialDef | None = None

    def copy(self) -> "GeometryBinding":
        return GeometryBinding(stateset_uid=self.stateset_uid, material=self.material)


def _parse_userdata_value(raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    try:
        return ast.literal_eval(raw)
    except Exception:
        return raw


def _as_rgba(val: Any, default: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)) -> tuple[float, float, float, float]:
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        r, g, b = float(val[0]), float(val[1]), float(val[2])
        a = float(val[3]) if len(val) > 3 else 1.0
        return (r, g, b, a)
    if isinstance(val, (int, float)):
        v = float(val)
        return (v, v, v, 1.0)
    return default


def _as_rgb(val: Any, default: tuple[float, float, float] = (0.0, 0.0, 0.0)) -> tuple[float, float, float]:
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        return (float(val[0]), float(val[1]), float(val[2]))
    return default


def _unwrap_stateset(node: Any) -> dict | None:
    if not isinstance(node, dict):
        return None
    if "osg.StateSet" in node and isinstance(node["osg.StateSet"], dict):
        return node["osg.StateSet"]
    if "UniqueID" in node or "AttributeList" in node or "UserDataContainer" in node:
        return node
    return None


def _material_from_stateset(ss: dict) -> MaterialDef | None:
    """Build MaterialDef from a *full* StateSet definition (not a UniqueID stub)."""
    uid = ss.get("UniqueID")
    if uid is None:
        return None
    # Pure reference stub — not a definition
    if set(ss.keys()) <= {"UniqueID"}:
        return None

    name = str(ss.get("Name") or "")
    factors: dict[str, Any] = {}
    for item in (ss.get("UserDataContainer") or {}).get("Values") or []:
        if isinstance(item, dict) and item.get("Name"):
            factors[str(item["Name"])] = _parse_userdata_value(item.get("Value"))

    for attr in ss.get("AttributeList") or []:
        if isinstance(attr, dict) and "osg.Material" in attr:
            mat = attr["osg.Material"]
            name = str(mat.get("Name") or name)
            if "Diffuse" in mat and "DiffuseColor" not in factors:
                factors["DiffuseColor"] = mat.get("Diffuse")

    if not name and not factors:
        return None

    diffuse = _as_rgba(factors.get("DiffuseColor"), (1.0, 1.0, 1.0, 1.0))
    # Sketchfab often stores DiffuseFactor as a scalar multiplier
    if "DiffuseFactor" in factors and isinstance(factors["DiffuseFactor"], (int, float)):
        df = float(factors["DiffuseFactor"])
        # Only apply when it looks like a multiplier (not already baked into color)
        if df < 0.999 and max(diffuse[:3]) > 0.99:
            diffuse = (df, df, df, diffuse[3])

    metallic = (
        float(factors["MetallicFactor"])
        if "MetallicFactor" in factors and factors["MetallicFactor"] is not None
        else 0.0
    )
    roughness = (
        float(factors["RoughnessFactor"])
        if "RoughnessFactor" in factors and factors["RoughnessFactor"] is not None
        else 0.6
    )
    emissive = _as_rgb(factors.get("EmissiveColor"), (0.0, 0.0, 0.0))
    ef = float(factors.get("EmissiveFactor", 0.0) or 0.0)
    if ef and emissive == (0.0, 0.0, 0.0):
        emissive = (ef, ef, ef)
    elif ef:
        emissive = (emissive[0] * ef, emissive[1] * ef, emissive[2] * ef)

    slot_raw = factors.get("UniqueID")
    try:
        slot_id = int(slot_raw) if slot_raw is not None else None
    except (TypeError, ValueError):
        slot_id = None

    return MaterialDef(
        stateset_uid=int(uid),
        name=name or f"material_{uid}",
        material_slot_id=slot_id,
        base_color_factor=diffuse,
        metallic_factor=metallic,
        roughness_factor=roughness,
        emissive_factor=emissive,
        double_sided=str(factors.get("doubleSided", "")).lower() == "true",
        alpha_mode=str(factors.get("alphaMode") or "OPAQUE"),
    )


def index_statesets(scene: Any) -> dict[int, MaterialDef]:
    """First pass: collect full StateSet definitions keyed by UniqueID."""
    registry: dict[int, MaterialDef] = {}

    def remember(ss: dict | None) -> None:
        if ss is None:
            return
        mat = _material_from_stateset(ss)
        if mat is None:
            return
        prev = registry.get(mat.stateset_uid)
        if prev is None or (mat.name and not prev.name):
            registry[mat.stateset_uid] = mat

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "osg.StateSet" in node:
                remember(node["osg.StateSet"])
            if "StateSet" in node:
                remember(_unwrap_stateset(node["StateSet"]))
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)

    visit(scene)
    return registry


def resolve_stateset_ref(
    stateset_node: Any,
    registry: dict[int, MaterialDef],
) -> GeometryBinding | None:
    """Resolve inline or UniqueID-only StateSet to a GeometryBinding."""
    ss = _unwrap_stateset(stateset_node)
    if ss is None:
        return None
    uid = ss.get("UniqueID")
    if uid is None:
        return None
    uid = int(uid)
    mat = registry.get(uid)
    if mat is None:
        # Inline definition not yet indexed (shouldn't happen after index pass)
        mat = _material_from_stateset(ss)
        if mat is not None:
            registry[uid] = mat
    return GeometryBinding(stateset_uid=uid, material=mat)


def binding_from_walk_node(
    node: dict,
    inherited: GeometryBinding | None,
    registry: dict[int, MaterialDef],
) -> GeometryBinding | None:
    ss = None
    if "StateSet" in node:
        ss = node["StateSet"]
    else:
        for key in ("osg.Node", "osg.MatrixTransform", "osg.Geometry", "Node", "MatrixTransform"):
            inner = node.get(key)
            if isinstance(inner, dict) and "StateSet" in inner:
                ss = inner["StateSet"]
                break
    if ss is None:
        return inherited
    resolved = resolve_stateset_ref(ss, registry)
    return resolved if resolved is not None else inherited


def bind_geometry(
    geom: dict,
    inherited: GeometryBinding | None,
    registry: dict[int, MaterialDef],
    by_name: dict[str, MaterialDef] | None = None,
) -> GeometryBinding:
    base = inherited.copy() if inherited else GeometryBinding()
    if "StateSet" in geom:
        resolved = resolve_stateset_ref(geom["StateSet"], registry)
        if resolved is not None:
            return resolved
    if by_name and base.material is None:
        # Meshes that carry no StateSet get a material Sketchfab named after the
        # node itself; exact name equality is the only case worth honouring.
        mat = by_name.get(str(geom.get("Name") or ""))
        if mat is not None:
            return GeometryBinding(stateset_uid=mat.stateset_uid, material=mat)
    return base


class StateSetBinder:
    """`osgjs.walk.GeometryBinder` backed by the indexed StateSet registry."""

    def __init__(
        self,
        registry: dict[int, MaterialDef],
        by_name: dict[str, MaterialDef] | None = None,
    ):
        self.registry = registry
        self.by_name = by_name or {}

    def for_node(self, node: dict, inherited: GeometryBinding | None) -> GeometryBinding | None:
        return binding_from_walk_node(node, inherited, self.registry)

    def for_geometry(self, geom: dict, inherited: GeometryBinding | None) -> GeometryBinding:
        return bind_geometry(geom, inherited, self.registry, self.by_name)
