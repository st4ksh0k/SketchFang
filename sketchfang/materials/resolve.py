"""
Join the server material table to indexed StateSets and finish glTF slots.

`prepare_materials` is the whole public surface: give it a scene and the
downloaded textures, get back the StateSet registry the walk needs plus the
materials no StateSet claimed (matched by name for meshes without one).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..api.options import fetch_options
from ..textures.models import TextureAsset
from ..util.log import log
from .bake import (
    bake_additive_glow,
    bake_clearcoat_tint,
    flip_normal_map_y,
    pack_metallic_roughness,
)
from .pbr import PbrMaterial, resolve_model_materials
from .sketchfab import UVTransform
from .stateset import GeometryBinding, MaterialDef, index_statesets


@dataclass(frozen=True)
class ResolvedMaterial:
    """glTF-oriented material description consumed by the GLB writer."""

    name: str
    base_color_uid: str | None = None
    normal_uid: str | None = None
    metallic_roughness_uid: str | None = None
    occlusion_uid: str | None = None
    emissive_uid: str | None = None
    base_color_factor: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    metallic_factor: float = 0.0
    roughness_factor: float = 0.6
    emissive_factor: tuple[float, float, float] = (0.0, 0.0, 0.0)
    double_sided: bool = False
    alpha_mode: str = "OPAQUE"
    alpha_cutoff: float = 0.5
    normal_scale: float = 1.0
    occlusion_strength: float = 1.0
    clearcoat_uid: str | None = None
    clearcoat_factor: float = 0.0
    clearcoat_roughness: float = 0.0
    uv_transforms: tuple[tuple[str, UVTransform], ...] = ()
    key: str = ""


# ---------------------------------------------------------------------------
# Server material -> MaterialDef
# ---------------------------------------------------------------------------

def _apply_additive(
    mat: MaterialDef,
    assets: dict[str, TextureAsset],
    *,
    output_dir: Path,
) -> None:
    glow_uid = mat.base_color_uid
    if not glow_uid:
        # Flat additive colour: emit it and let the surface itself vanish.
        mat.emissive_factor = mat.base_color_factor[:3]
        mat.base_color_factor = (0.0, 0.0, 0.0, mat.base_color_factor[3])
        return

    mat.emissive_uid = glow_uid
    mat.emissive_factor = (1.0, 1.0, 1.0)
    if "baseColor" in mat.uv_transforms:
        mat.uv_transforms["emissive"] = mat.uv_transforms["baseColor"]
    masked = bake_additive_glow(assets, glow_uid, output_dir=output_dir)
    if masked:
        mat.base_color_uid = masked
    mat.base_color_factor = (0.0, 0.0, 0.0, 1.0)


def _apply_clearcoat(
    mat: MaterialDef,
    pbr: PbrMaterial,
    assets: dict[str, TextureAsset],
    *,
    output_dir: Path,
) -> None:
    mat.clearcoat_factor = pbr.clearcoat_factor
    mat.clearcoat_roughness = pbr.clearcoat_roughness
    if pbr.clearcoat is not None and pbr.clearcoat.uid in assets:
        mat.clearcoat_uid = pbr.clearcoat.uid

    if pbr.coat_absorption is None:
        return

    mask_uid = mat.clearcoat_uid
    base_uv = pbr.base_color.uv if pbr.base_color else UVTransform()
    coat_uv = pbr.clearcoat.uv if pbr.clearcoat else UVTransform()
    if mask_uid and coat_uv != base_uv:
        # Baking two maps together only works while they share a UV mapping.
        return

    if not mat.base_color_uid and not mask_uid:
        # Uniform coat over a flat colour: fold it straight into the factor.
        r, g, b, a = mat.base_color_factor
        f = pbr.clearcoat_factor
        tint = [1.0 - f * (1.0 - c) for c in pbr.coat_absorption]
        mat.base_color_factor = (r * tint[0], g * tint[1], b * tint[2], a)
        return

    baked = bake_clearcoat_tint(
        assets,
        mat.base_color_uid,
        mask_uid,
        pbr.coat_absorption,
        pbr.clearcoat_factor,
        output_dir=output_dir,
    )
    if baked:
        mat.base_color_uid = baked


def _apply_pbr(
    mat: MaterialDef,
    pbr: PbrMaterial,
    assets: dict[str, TextureAsset],
    *,
    output_dir: Path,
) -> int:
    """Copy one resolved server material onto a MaterialDef. Returns slots filled."""

    def ref(t) -> str | None:
        return t.uid if t is not None and t.uid in assets else None

    mat.name = pbr.name or mat.name
    mat.base_color_factor = pbr.base_color_factor
    mat.metallic_factor = pbr.metallic_factor
    mat.roughness_factor = pbr.roughness_factor
    mat.emissive_factor = pbr.emissive_factor
    mat.double_sided = pbr.double_sided
    mat.alpha_mode = pbr.alpha_mode
    mat.alpha_cutoff = pbr.alpha_cutoff
    mat.normal_scale = pbr.normal_scale
    mat.occlusion_strength = pbr.occlusion_strength

    mat.base_color_uid = ref(pbr.base_color)
    mat.normal_uid = ref(pbr.normal)
    mat.occlusion_uid = ref(pbr.occlusion)
    mat.emissive_uid = ref(pbr.emissive)
    mat.metallic_uid = ref(pbr.metallic)
    mat.roughness_uid = ref(pbr.roughness)

    if mat.normal_uid and pbr.normal_flip_y:
        flipped = flip_normal_map_y(assets, mat.normal_uid, output_dir=output_dir)
        if flipped:
            mat.normal_uid = flipped

    mat.uv_transforms = {
        slot: t.uv
        for slot, t in (
            ("baseColor", pbr.base_color),
            ("normal", pbr.normal),
            ("occlusion", pbr.occlusion),
            ("emissive", pbr.emissive),
            ("metallicRoughness", pbr.metallic or pbr.roughness),
        )
        if t is not None and not t.uv.is_identity
    }

    mat.metallic_roughness_uid = pack_metallic_roughness(
        assets,
        mat.metallic_uid,
        mat.roughness_uid,
        output_dir=output_dir,
        invert_roughness=pbr.roughness_is_glossiness,
    )

    _apply_clearcoat(mat, pbr, assets, output_dir=output_dir)
    if pbr.additive:
        _apply_additive(mat, assets, output_dir=output_dir)

    return sum(
        1
        for uid in (
            mat.base_color_uid,
            mat.normal_uid,
            mat.occlusion_uid,
            mat.emissive_uid,
            mat.metallic_roughness_uid,
        )
        if uid
    )


def apply_material_options(
    registry: dict[int, MaterialDef],
    options: dict,
    assets: dict[str, TextureAsset],
    *,
    output_dir: Path,
    progress: bool = True,
) -> dict[str, MaterialDef]:
    """
    Bind textures using the server material table.

    Every StateSet carries its material's `stateSetID` in UserData as
    `UniqueID`, so this is an exact join — no filename inspection anywhere.

    Returns the server materials that no StateSet claimed, keyed by name, for
    meshes that carry no StateSet of their own.
    """
    by_slot = resolve_model_materials(options)
    if not by_slot:
        return {}

    matched = 0
    textured = 0
    claimed: set[int] = set()
    for mat in registry.values():
        pbr = by_slot.get(mat.material_slot_id) if mat.material_slot_id else None
        if pbr is None:
            continue
        matched += 1
        claimed.add(pbr.state_set_id)
        if _apply_pbr(mat, pbr, assets, output_dir=output_dir):
            textured += 1

    orphans: dict[str, MaterialDef] = {}
    for slot_id, pbr in by_slot.items():
        if slot_id in claimed:
            continue
        mat = MaterialDef(
            stateset_uid=-1 - slot_id, name=pbr.name, material_slot_id=slot_id
        )
        _apply_pbr(mat, pbr, assets, output_dir=output_dir)
        orphans[pbr.name] = mat

    if progress:
        unmatched = len(registry) - matched
        note = f", {unmatched} unmatched" if unmatched else ""
        extra = f", {len(orphans)} by name" if orphans else ""
        log(
            f"[*] Resolved {matched}/{len(registry)} material(s) from the server "
            f"table ({textured} with textures{note}{extra})"
        )
    return orphans


# ---------------------------------------------------------------------------
# MaterialDef -> ResolvedMaterial (GLB facing)
# ---------------------------------------------------------------------------

def resolve_material(
    binding: GeometryBinding,
    assets: dict[str, TextureAsset],
) -> ResolvedMaterial:
    mat = binding.material
    if mat is None:
        return fallback_material(assets)

    def ok(uid: str | None) -> str | None:
        return uid if uid and uid in assets else None

    return ResolvedMaterial(
        name=mat.name,
        base_color_uid=ok(mat.base_color_uid),
        normal_uid=ok(mat.normal_uid),
        metallic_roughness_uid=ok(mat.metallic_roughness_uid),
        occlusion_uid=ok(mat.occlusion_uid),
        emissive_uid=ok(mat.emissive_uid),
        base_color_factor=mat.base_color_factor,
        metallic_factor=mat.metallic_factor,
        roughness_factor=mat.roughness_factor,
        emissive_factor=mat.emissive_factor,
        double_sided=mat.double_sided,
        alpha_mode=mat.alpha_mode,
        alpha_cutoff=mat.alpha_cutoff,
        normal_scale=mat.normal_scale,
        occlusion_strength=mat.occlusion_strength,
        clearcoat_uid=ok(mat.clearcoat_uid),
        clearcoat_factor=mat.clearcoat_factor,
        clearcoat_roughness=mat.clearcoat_roughness,
        uv_transforms=tuple(sorted(mat.uv_transforms.items())),
        key=mat.key,
    )


def fallback_material(assets: dict[str, TextureAsset]) -> ResolvedMaterial:
    """Unbound mesh — solid grey, do NOT slap a random texture on it."""
    return ResolvedMaterial(
        name="default",
        base_color_factor=(0.75, 0.75, 0.75, 1.0),
        key="untextured",
    )


def prepare_materials(
    scene: Any,
    assets: dict[str, TextureAsset],
    *,
    uid: str | None = None,
    options: dict | None = None,
    progress: bool = True,
    output_dir: Path | None = None,
) -> tuple[dict[int, MaterialDef], dict[str, MaterialDef]]:
    """Index StateSets, then bind textures from the server material table."""
    registry = index_statesets(scene)
    if progress:
        log(f"[*] Indexed {len(registry)} material StateSet(s)")

    if options is None and uid:
        try:
            options = fetch_options(uid)
        except Exception as exc:
            if progress:
                log(f"[!] Material options unavailable ({exc}); factors only")
            options = None

    by_name: dict[str, MaterialDef] = {}
    if options:
        out_dir = output_dir or next(
            (a.path.parent.parent for a in assets.values()), Path(".")
        )
        by_name = apply_material_options(
            registry, options, assets, output_dir=out_dir, progress=progress
        )
    return registry, by_name
