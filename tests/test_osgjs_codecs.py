"""OSGJS codecs are pure functions — no network, no WASM, no Pillow."""

from __future__ import annotations

import math

from sketchfang.osgjs.buffers import decode_varint, parse_userdata, read_array_buffer
from sketchfang.osgjs.codecs import (
    delta_decode,
    dequantize,
    implicit_expand,
    predict_vertices,
    strip_to_triangles,
    unpack_normals,
    watermark_decode_u16,
)


def test_parse_userdata_decodes_json_values():
    geom = {
        "UserDataContainer": {
            "Values": [
                {"Name": "attributes", "Value": "17"},
                {"Name": "wireframe", "Value": "not json"},
            ]
        }
    }
    assert parse_userdata(geom) == {"attributes": 17, "wireframe": "not json"}


def test_decode_varint_zigzags_signed_types():
    # 1 -> zigzag 1 decodes to -1; unsigned types keep the raw value
    assert decode_varint(bytes([1]), 0, 1, "Int32Array") == [-1]
    assert decode_varint(bytes([1]), 0, 1, "Uint32Array") == [1]


def test_read_array_buffer_reads_inline_elements():
    meta = {"Float32Array": {"Size": 2, "Elements": [1.0, 2.0, 3.0, 4.0]}}
    assert read_array_buffer(meta, 2, {}) == [1.0, 2.0, 3.0, 4.0]


def test_delta_decode_accumulates_zigzag_deltas():
    assert delta_decode([10, 2, 4]) == [10, 11, 13]


def test_watermark_decode_tracks_high_water_mark():
    state = [0]
    assert watermark_decode_u16([0, 0], state) == [0, 1]
    assert state == [2]


def test_implicit_expand_fills_gaps_with_running_index():
    # header: [out_len, mask_len, first_expected], then the mask, then the stream
    src = [4, 1, 5, 0b1010, 100, 200]
    assert implicit_expand(src, 4, 4, False) == [100, 5, 200, 6]


def test_strip_to_triangles_flips_winding_and_drops_degenerates():
    assert strip_to_triangles([0, 1, 2, 3]) == [0, 1, 2, 1, 3, 2]
    assert strip_to_triangles([0, 1, 1, 2]) == []


def test_predict_vertices_completes_the_parallelogram():
    verts = [0, 0, 1, 0, 0, 1, 0, 0]
    predict_vertices(verts, 2, [0, 1, 2, 3])
    assert verts[6:] == [1, 1]


def test_dequantize_applies_bbox_origin_and_step():
    assert dequantize([0, 1], 1, [2.0], [0.5]) == [2.0, 2.5]


def test_unpack_normals_returns_unit_vectors():
    out = unpack_normals([0, 0])
    assert len(out) == 3
    assert math.isclose(math.dist(out, (0.0, 0.0, 0.0)), 1.0, rel_tol=1e-6)
