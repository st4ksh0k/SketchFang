"""Project a server material onto glTF 2.0 metallic-roughness."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .sketchfab import (
    Channel,
    SketchfabMaterial,
    UVTransform,
    as_float,
    as_vec3,
    parse_materials,
    renderer_of,
)


@dataclass
class TextureRef:
    uid: str
    tex_coord_unit: int = 0
    uv: UVTransform = UVTransform()


@dataclass
class PbrMaterial:
    """A SketchfabMaterial projected onto glTF 2.0 metallic-roughness."""

    name: str
    state_set_id: int
    base_color_factor: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    base_color: TextureRef | None = None
    metallic_factor: float = 0.0
    roughness_factor: float = 1.0
    metallic: TextureRef | None = None
    roughness: TextureRef | None = None
    # Sketchfab stores gloss for the spec/gloss workflow; roughness = 1 - gloss
    roughness_is_glossiness: bool = False
    normal: TextureRef | None = None
    normal_scale: float = 1.0
    normal_flip_y: bool = False
    occlusion: TextureRef | None = None
    occlusion_strength: float = 1.0
    emissive: TextureRef | None = None
    emissive_factor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    # Opacity type "additive" renders with BlendFunc(ONE, ONE) — a glow that
    # ignores alpha. glTF has no additive mode, so the caller re-expresses it.
    additive: bool = False
    double_sided: bool = False
    clearcoat_factor: float = 0.0
    clearcoat_roughness: float = 0.0
    clearcoat: TextureRef | None = None
    # Sketchfab's clear coat can be tinted, which is how many uploads carry
    # their paint colour. glTF's clear coat is colourless, so this absorption
    # gets baked into base colour instead.
    coat_absorption: tuple[float, float, float] | None = None


def clearcoat_absorption(
    tint: tuple[float, float, float], thickness: float
) -> tuple[float, float, float]:
    """
    Light transmitted through a tinted clear coat, at normal incidence.

    Viewer (1c76918338bfe04b43c19e45141a8782-v2.js):

        updateTintUniform:  sigma = -log(clamp(tint, .01, .99)) / max(20 - thickness, .01)
        beerLambert:        exp(sigma * -(thickness * (NoL + NoV) / (NoL * NoV)))

    Setting NoL = NoV = 1 makes the view-dependent term equal 2, which gives a
    single colour that can be multiplied into a base colour map.
    """
    denom = max(20.0 - thickness, 0.01)
    out = []
    for c in tint:
        sigma = -math.log(min(max(c, 0.01), 0.99)) / denom
        out.append(math.exp(-sigma * thickness * 2.0))
    return (out[0], out[1], out[2])


def _tex_ref(ch: Channel) -> TextureRef | None:
    if not ch.has_texture:
        return None
    return TextureRef(
        uid=ch.texture_uid,  # type: ignore[arg-type]
        tex_coord_unit=ch.tex_coord_unit,
        uv=ch.uv,
    )


def _base_color_channel(mat: SketchfabMaterial, renderer: str) -> Channel:
    """Viewer: PBR reads AlbedoPBR / DiffusePBR, CLASSIC reads DiffuseColor."""
    if renderer == "classic":
        return mat.channel("DiffuseColor")
    metal = mat.is_metalness_workflow
    primary = mat.channel("AlbedoPBR" if metal else "DiffusePBR")
    if primary.enable:
        return primary
    # Some uploads only populate the classic slot; the viewer copies it across
    # (copyDiffuse / channelTextureCopy DiffuseColor -> AlbedoPBR, DiffusePBR).
    for fallback in ("AlbedoPBR", "DiffusePBR", "DiffuseColor"):
        ch = mat.channel(fallback)
        if ch.has_texture or ch.color is not None:
            return ch
    return primary


def to_pbr(mat: SketchfabMaterial, *, renderer: str = "pbr") -> PbrMaterial:
    """Project a server material onto glTF metallic-roughness."""
    out = PbrMaterial(
        name=mat.name,
        state_set_id=mat.state_set_id,
        double_sided=mat.double_sided,
    )

    base = _base_color_channel(mat, renderer)
    rgb = base.color if base.color is not None else (1.0, 1.0, 1.0)
    # Sketchfab evaluates a channel as color * factor; glTF folds both into
    # baseColorFactor, which also multiplies baseColorTexture.
    scale = base.factor if base.factor is not None else 1.0
    out.base_color_factor = (rgb[0] * scale, rgb[1] * scale, rgb[2] * scale, 1.0)
    out.base_color = _tex_ref(base)

    metalness = mat.channel("MetalnessPBR")
    if mat.is_metalness_workflow:
        out.metallic_factor = metalness.factor
        out.metallic = _tex_ref(metalness)
    else:
        # Spec/gloss has no glTF metallic equivalent without KHR_materials_
        # pbrSpecularGlossiness (archived); dielectric is the closest match.
        out.metallic_factor = 0.0

    rough = mat.channel("RoughnessPBR")
    gloss = mat.channel("GlossinessPBR")
    if rough.enable:
        out.roughness_factor = rough.factor
        out.roughness = _tex_ref(rough)
    elif gloss.enable:
        out.roughness_is_glossiness = True
        out.roughness = _tex_ref(gloss)
        # Without a map the inversion is exact; with one it is baked at pack time.
        out.roughness_factor = 1.0 if out.roughness else 1.0 - gloss.factor
    else:
        out.roughness_factor = 1.0

    normal = mat.channel("NormalMap")
    if normal.has_texture:
        out.normal = _tex_ref(normal)
        out.normal_scale = normal.factor
        out.normal_flip_y = bool(normal.raw.get("flipY"))

    ao = mat.channel("AOPBR")
    if not ao.has_texture:
        ao = mat.channel("DiffuseIntensity")  # CLASSIC equivalent
    if ao.has_texture:
        out.occlusion = _tex_ref(ao)
        out.occlusion_strength = ao.factor

    emit = mat.channel("EmitColor")
    if emit.enable:
        color = emit.color or (1.0, 1.0, 1.0)
        f = emit.factor
        out.emissive_factor = (color[0] * f, color[1] * f, color[2] * f)
        out.emissive = _tex_ref(emit)

    coat = mat.channel("ClearCoat")
    if coat.enable and coat.factor > 0.0:
        out.clearcoat_factor = coat.factor
        out.clearcoat_roughness = mat.channel("ClearCoatRoughness").factor
        out.clearcoat = _tex_ref(coat)
        tint = coat.raw.get("tint")
        thickness = as_float(coat.raw.get("thickness"), 0.0)
        rgb = as_vec3(tint)
        if rgb and thickness > 0.0 and min(rgb) < 0.99:
            out.coat_absorption = clearcoat_absorption(rgb, thickness)

    alpha_mask = mat.channel("AlphaMask")
    opacity = mat.channel("Opacity")
    if alpha_mask.enable:
        out.alpha_mode = "MASK"
        out.alpha_cutoff = alpha_mask.factor
    elif opacity.enable and _opacity_is_effective(opacity):
        otype = str(opacity.raw.get("type") or "").lower()
        out.alpha_mode = "BLEND"
        if otype == "additive":
            out.additive = True
        else:
            r, g, b, _ = out.base_color_factor
            out.base_color_factor = (r, g, b, opacity.factor)

    return out


def _opacity_is_effective(opacity: Channel) -> bool:
    """Port of the viewer's Opacity.isEffective() (sans vertex-alpha / SSS)."""
    otype = str(opacity.raw.get("type") or "").lower()
    if otype == "dithering":
        return True
    if otype in ("alphablend", "refraction"):
        return opacity.has_texture or float(opacity.factor) != 1.0
    # additive / unspecified: enabled channel is enough
    return True


def resolve_model_materials(options: dict) -> dict[int, PbrMaterial]:
    """`stateSetID -> PbrMaterial` for a whole model."""
    renderer = renderer_of(options)
    return {
        ss_id: to_pbr(mat, renderer=renderer)
        for ss_id, mat in parse_materials(options).items()
    }
