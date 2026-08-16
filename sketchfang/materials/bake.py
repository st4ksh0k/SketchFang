"""
Every Pillow write in the material path lives here.

Sketchfab shades things glTF cannot express directly — separate metal/rough
maps, tinted clear coat, additive glow — so each bake collapses one of those
into a derived texture and registers it as a new asset.
"""

from __future__ import annotations

from pathlib import Path

from ..textures.models import TextureAsset


def _pillow():
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return None, None
    return Image, ImageChops


def _register(
    assets: dict[str, TextureAsset],
    uid: str,
    name: str,
    image,
    output_dir: Path,
) -> str:
    path = output_dir / "textures" / f"{uid}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)
    assets[uid] = TextureAsset(
        uid=uid,
        name=name,
        path=path,
        width=image.size[0],
        height=image.size[1],
        mime="image/png",
    )
    return uid


def pack_metallic_roughness(
    assets: dict[str, TextureAsset],
    metallic_uid: str | None,
    roughness_uid: str | None,
    *,
    output_dir: Path,
    invert_roughness: bool = False,
) -> str | None:
    """
    Pack Sketchfab's separate MetalnessPBR / RoughnessPBR maps into one glTF
    metallicRoughnessTexture (G = roughness, B = metallic). Returns new asset uid.

    `invert_roughness` handles the spec/gloss workflow, where the server stores
    GlossinessPBR and roughness is its complement.
    """
    if metallic_uid and metallic_uid not in assets:
        metallic_uid = None
    if roughness_uid and roughness_uid not in assets:
        roughness_uid = None
    if not metallic_uid and not roughness_uid:
        return None

    Image, ImageChops = _pillow()
    if Image is None:
        return None

    uid = f"mr_{metallic_uid or 'x'}_{roughness_uid or 'x'}{'_inv' if invert_roughness else ''}"
    if uid in assets:
        return uid

    metal_img = Image.open(assets[metallic_uid].path).convert("L") if metallic_uid else None
    rough_img = Image.open(assets[roughness_uid].path).convert("L") if roughness_uid else None
    if rough_img is not None and invert_roughness:
        rough_img = ImageChops.invert(rough_img)

    if metal_img and rough_img and metal_img.size != rough_img.size:
        # Match the larger map; viewer samples independently but glTF needs one size
        w = max(metal_img.size[0], rough_img.size[0])
        h = max(metal_img.size[1], rough_img.size[1])
        metal_img = metal_img.resize((w, h))
        rough_img = rough_img.resize((w, h))
    size = (metal_img or rough_img).size  # type: ignore[union-attr]
    if metal_img is None:
        metal_img = Image.new("L", size, 255)
    if rough_img is None:
        rough_img = Image.new("L", size, 255)

    packed = Image.merge("RGB", (Image.new("L", size, 255), rough_img, metal_img))
    return _register(assets, uid, f"packed_metallicRoughness_{uid}.png", packed, output_dir)


def bake_clearcoat_tint(
    assets: dict[str, TextureAsset],
    base_uid: str | None,
    mask_uid: str | None,
    absorption: tuple[float, float, float],
    coat_factor: float,
    *,
    output_dir: Path,
) -> str | None:
    """
    Multiply a tinted clear coat into the base colour map.

    The viewer shades `albedo * mix(1, coatAbsorption, coatMask)`; glTF clear
    coat carries no tint, so the same product is baked here. Returns the uid of
    the derived texture, or None when there is nothing to bake into.
    """
    if not base_uid and not mask_uid:
        return None

    Image, _ = _pillow()
    if Image is None:
        return None

    tag = "".join(f"{round(c * 255):02x}" for c in absorption)
    uid = f"cc_{base_uid or 'x'}_{mask_uid or 'x'}_{tag}"
    if uid in assets:
        return uid

    base = (
        Image.open(assets[base_uid].path).convert("RGB")
        if base_uid and base_uid in assets
        else None
    )
    mask = (
        Image.open(assets[mask_uid].path).convert("L")
        if mask_uid and mask_uid in assets
        else None
    )
    if base is None and mask is None:
        return None
    if base is None:
        base = Image.new("RGB", mask.size, (255, 255, 255))  # type: ignore[union-attr]
    if mask is None:
        mask = Image.new("L", base.size, 255)
    elif mask.size != base.size:
        mask = mask.resize(base.size, Image.LANCZOS)
    if coat_factor < 1.0:
        mask = mask.point(lambda v: int(v * coat_factor))

    channels = []
    for i, ch in enumerate(base.split()):
        tinted = ch.point(lambda v, s=absorption[i]: min(255, int(round(v * s))))
        channels.append(Image.composite(tinted, ch, mask))
    baked = Image.merge("RGB", channels)

    return _register(assets, uid, f"clearcoat_baseColor_{uid}.png", baked, output_dir)


def flip_normal_map_y(
    assets: dict[str, TextureAsset],
    source_uid: str,
    *,
    output_dir: Path,
) -> str | None:
    """
    Invert the green channel of a normal map (DirectX → OpenGL).

    Sketchfab's NormalMap ``flipY`` flag means the viewer negates N.y when
    sampling; glTF expects OpenGL-style maps, so bake the flip into the texels.
    """
    if source_uid not in assets:
        return None

    Image, ImageChops = _pillow()
    if Image is None:
        return None

    uid = f"nmap_fy_{source_uid}"
    if uid in assets:
        return uid

    src = Image.open(assets[source_uid].path).convert("RGBA")
    r, g, b, a = src.split()
    flipped = Image.merge("RGBA", (r, ImageChops.invert(g), b, a))
    return _register(assets, uid, f"normal_flipY_{source_uid}.png", flipped, output_dir)


def bake_additive_glow(
    assets: dict[str, TextureAsset],
    source_uid: str,
    *,
    output_dir: Path,
) -> str | None:
    """
    Re-express an additive glow map as an alpha-blended one.

    Sketchfab draws these with BlendFunc(ONE, ONE), so black is invisible and
    bright pixels add light. The nearest glTF equivalent is a blended surface
    whose alpha follows the map's luminance, with the colour moved to emissive:
    `dst*(1-L) + glow*L` instead of `dst + glow`.
    """
    if source_uid not in assets:
        return None

    Image, _ = _pillow()
    if Image is None:
        return None

    uid = f"glow_{source_uid}"
    if uid in assets:
        return uid

    src = Image.open(assets[source_uid].path).convert("RGB")
    luminance = src.convert("L")
    black = Image.new("L", src.size, 0)
    masked = Image.merge("RGBA", (black, black, black, luminance))

    return _register(assets, uid, f"additive_alpha_{source_uid}.png", masked, output_dir)
