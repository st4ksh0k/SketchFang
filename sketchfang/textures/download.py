"""Download texture images into `<output_dir>/textures`, decoding scrambled ones."""

from __future__ import annotations

from pathlib import Path

from ..api.client import fetch_bytes
from ..api.textures import fetch_texture_list
from ..util.log import log
from .listing import parse_texture_listing
from .models import MIME_BY_EXT, TextureAsset, TextureInfo
from .unscramble import unscramble_image


def _require_pillow():
    try:
        from PIL import Image
    except ImportError as exc:
        raise RuntimeError("Missing dependency: pip install pillow") from exc
    return Image


def download_textures(
    infos: list[TextureInfo],
    output_dir: Path,
    *,
    progress: bool = True,
) -> dict[str, TextureAsset]:
    Image = _require_pillow()

    tex_dir = output_dir / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    assets: dict[str, TextureAsset] = {}
    for info in infos:
        # Always write decoded PNG when pk-protected (viewer GPU path)
        local = tex_dir / (
            f"{info.uid}.png" if info.pk is not None else f"{info.uid}{info.ext}"
        )
        marker = tex_dir / f".{info.uid}.decoded"
        need_fetch = not local.exists() or (info.pk is not None and not marker.exists())

        if need_fetch:
            if progress:
                pk_note = f" pk={info.pk}" if info.pk is not None else ""
                log(
                    f"[*] Texture {info.name} ({info.width}x{info.height}"
                    f"{pk_note}) -> {local.name}"
                )
            raw_path = tex_dir / f".{info.uid}.raw{info.ext}"
            raw_path.write_bytes(fetch_bytes(info.url))
            if info.pk is not None:
                if progress:
                    log(f"[*] Unscrambling {info.name} (viewer pk shader)")
                img = Image.open(raw_path)
                # flip_y only: the shader renders into a GL framebuffer whose
                # origin is bottom-left, so reading it back as a top-left PNG
                # needs the row flip. X must stay untouched or the silkscreen
                # lands on the wrong side of the board.
                decoded = unscramble_image(img, info.pk, flip_y=True, flip_x=False)
                decoded.save(local)
                marker.write_text(str(info.pk))
                try:
                    raw_path.unlink()
                except OSError:
                    pass
            else:
                if local != raw_path:
                    local.write_bytes(raw_path.read_bytes())
                    try:
                        raw_path.unlink()
                    except OSError:
                        pass
        elif progress:
            log(f"[*] Texture {info.name} (cached) -> {local.name}")

        w, h = info.width, info.height
        if local.exists():
            try:
                with Image.open(local) as im:
                    w, h = im.size
            except Exception:
                pass

        assets[info.uid] = TextureAsset(
            uid=info.uid,
            name=info.name,
            path=local,
            width=w,
            height=h,
            mime="image/png" if local.suffix.lower() == ".png" else MIME_BY_EXT.get(info.ext, "image/jpeg"),
            pk=info.pk,
        )
    return assets


def extract_textures(
    uid: str,
    output_dir: Path,
    *,
    progress: bool = True,
) -> dict[str, TextureAsset]:
    """Listing → best variants → downloaded assets keyed by texture uid."""
    listing = fetch_texture_list(uid, progress=progress)
    infos = parse_texture_listing(listing)
    if progress:
        log(f"[*] Texture listing: {len(infos)} asset(s)")
    return download_textures(infos, output_dir, progress=progress)
