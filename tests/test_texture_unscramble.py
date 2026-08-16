"""The viewer `pk` unscramble must be a pure pixel permutation."""

from __future__ import annotations

from PIL import Image

from sketchfang.textures.unscramble import pk_offset, unscramble_image


def _gradient(width: int, height: int) -> Image.Image:
    img = Image.new("RGBA", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            i = y * width + x
            px[x, y] = (i % 256, (i // 256) % 256, x % 256, 255)
    return img


def test_pk_offset_wraps_at_the_pixel_count():
    assert pk_offset(3, 16, 16) == -192
    assert pk_offset(4, 16, 16) == -0


def test_unscramble_is_a_permutation_of_the_source_pixels():
    src = _gradient(16, 16)
    out = unscramble_image(src, 7)
    assert sorted(out.getdata()) == sorted(src.getdata())


def test_flip_y_mirrors_rows_of_the_unflipped_result():
    src = _gradient(16, 16)
    flat = unscramble_image(src, 5, flip_y=False)
    flipped = unscramble_image(src, 5, flip_y=True)
    height = src.size[1]
    for y in range(height):
        assert list(flipped.crop((0, y, 16, y + 1)).getdata()) == list(
            flat.crop((0, height - 1 - y, 16, height - y)).getdata()
        )


def test_images_smaller_than_one_tile_pass_through():
    src = _gradient(4, 4)
    assert list(unscramble_image(src, 3).getdata()) == list(src.convert("RGBA").getdata())
