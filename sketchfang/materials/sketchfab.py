"""
The server's own material description.

EDUCATIONAL USE ONLY. For studying Sketchfab's viewer material path; not for
redistributing protected assets. Comply with Sketchfab ToS and copyright.

`GET /i/models/{uid}/options` returns the same shading state the viewer itself
loads: every material with its `stateSetID` plus the full channel table
(enable / factor / color / texture uid / UVTransforms). A geometry's OSGJS
StateSet carries that same id in `UserDataContainer` as `UniqueID`, so binding
a texture to a mesh is a lookup rather than a filename guess.

Viewer rules reproduced here, from
``.sketchfab_cache/1c76918338bfe04b43c19e45141a8782-v2.js``:

  enforceWorkflow()
      metalness            = MetalnessPBR.enable
      AlbedoPBR.enable     = metalness    DiffusePBR.enable  = !metalness
      SpecularF0.enable    = metalness    SpecularPBR.enable = !metalness
      GlossinessPBR.enable = !RoughnessPBR.enable
      NormalMap.enable disables BumpMap

  getRenderTypeMask() — which channels a given renderer actually reads
      PBR      : DiffusePBR AlbedoPBR AOPBR CavityPBR
      PBR_LIT  : SpecularPBR MetalnessPBR GlossinessPBR RoughnessPBR
                 SpecularF0 ClearCoat* Anisotropy Sheen*
      CLASSIC  : DiffuseColor DiffuseIntensity
      LIT|...  : Opacity AlphaMask Displacement EmitColor NormalMap BumpMap

  isSRGB(): DiffuseColor DiffusePBR AlbedoPBR EmitColor SpecularColor
            SpecularPBR Matcap Sheen
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UVTransform:
    scale: tuple[float, float] = (1.0, 1.0)
    offset: tuple[float, float] = (0.0, 0.0)
    rotation: float = 0.0

    @property
    def is_identity(self) -> bool:
        return (
            self.scale == (1.0, 1.0)
            and self.offset == (0.0, 0.0)
            and self.rotation == 0.0
        )


@dataclass(frozen=True)
class Channel:
    """One entry of a material's `channels` table."""

    name: str
    enable: bool = False
    factor: float = 1.0
    color: tuple[float, float, float] | None = None
    texture_uid: str | None = None
    tex_coord_unit: int = 0
    uv: UVTransform = UVTransform()
    internal_format: str = "RGB"
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def has_texture(self) -> bool:
        return bool(self.enable and self.texture_uid)


EMPTY_CHANNEL = Channel(name="")


@dataclass
class SketchfabMaterial:
    """A material exactly as the server describes it."""

    material_id: str
    name: str
    state_set_id: int
    channels: dict[str, Channel]
    cull_face: str = "BACK"
    shadeless: bool = False

    def channel(self, name: str) -> Channel:
        return self.channels.get(name, EMPTY_CHANNEL)

    @property
    def is_metalness_workflow(self) -> bool:
        """Viewer enforceWorkflow: MetalnessPBR.enable selects the workflow."""
        return self.channel("MetalnessPBR").enable

    @property
    def double_sided(self) -> bool:
        return self.cull_face.upper() in ("DISABLE", "DISABLED", "NONE")


def as_float(val: Any, default: float = 0.0) -> float:
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def as_vec3(val: Any) -> tuple[float, float, float] | None:
    if isinstance(val, (list, tuple)) and len(val) >= 3:
        return (as_float(val[0]), as_float(val[1]), as_float(val[2]))
    return None


def as_vec2(val: Any, default: tuple[float, float]) -> tuple[float, float]:
    if isinstance(val, (list, tuple)) and len(val) >= 2:
        return (as_float(val[0]), as_float(val[1]))
    return default


def parse_channel(name: str, raw: Any) -> Channel:
    if not isinstance(raw, dict):
        return Channel(name=name)
    tex = raw.get("texture") if isinstance(raw.get("texture"), dict) else {}
    uvt = raw.get("UVTransforms") if isinstance(raw.get("UVTransforms"), dict) else {}
    return Channel(
        name=name,
        enable=bool(raw.get("enable")),
        factor=as_float(raw.get("factor"), 1.0),
        color=as_vec3(raw.get("color")),
        texture_uid=(str(tex["uid"]).lower() if tex.get("uid") else None),
        tex_coord_unit=int(tex.get("texCoordUnit") or 0),
        uv=UVTransform(
            scale=as_vec2(uvt.get("scale"), (1.0, 1.0)),
            offset=as_vec2(uvt.get("offset"), (0.0, 0.0)),
            rotation=as_float(uvt.get("rotation"), 0.0),
        ),
        internal_format=str(tex.get("internalFormat") or "RGB").upper(),
        raw=raw,
    )


def parse_materials(options: dict) -> dict[int, SketchfabMaterial]:
    """Build `stateSetID -> SketchfabMaterial` from the options payload."""
    out: dict[int, SketchfabMaterial] = {}
    for key, entry in (options.get("materials") or {}).items():
        if not isinstance(entry, dict) or "channels" not in entry:
            continue  # e.g. the "updatedAt" sibling key
        ss_id = entry.get("stateSetID")
        if ss_id is None:
            continue
        out[int(ss_id)] = SketchfabMaterial(
            material_id=str(entry.get("id") or key),
            name=str(entry.get("name") or f"material_{ss_id}"),
            state_set_id=int(ss_id),
            channels={
                name: parse_channel(name, raw)
                for name, raw in (entry["channels"] or {}).items()
            },
            cull_face=str(entry.get("cullFace") or "BACK"),
            shadeless=bool(entry.get("shadeless")),
        )
    return out


def renderer_of(options: dict) -> str:
    shading = options.get("shading") or {}
    return str(shading.get("renderer") or "pbr").lower()
