"""Server channels → glTF metallic-roughness, and the StateSet join."""

from __future__ import annotations

import math

from sketchfang.materials.pbr import clearcoat_absorption, resolve_model_materials, to_pbr
from sketchfang.materials.sketchfab import parse_materials
from sketchfang.materials.stateset import StateSetBinder, index_statesets


def options_with(channels: dict, *, state_set_id: int = 7, **material) -> dict:
    return {
        "shading": {"renderer": "pbr"},
        "materials": {
            "updatedAt": "ignored — not a material",
            "mat-1": {
                "id": "mat-1",
                "name": "paint",
                "stateSetID": state_set_id,
                "channels": channels,
                **material,
            },
        },
    }


def test_parse_materials_skips_non_material_keys():
    mats = parse_materials(options_with({"AlbedoPBR": {"enable": True}}))
    assert list(mats) == [7]
    assert mats[7].name == "paint"


def test_metalness_workflow_reads_albedo_and_metalness():
    options = options_with(
        {
            "MetalnessPBR": {"enable": True, "factor": 0.8},
            "AlbedoPBR": {
                "enable": True,
                "factor": 0.5,
                "color": [1.0, 0.5, 0.0],
                "texture": {"uid": "ABC123", "texCoordUnit": 0},
            },
            "RoughnessPBR": {"enable": True, "factor": 0.25},
        }
    )
    pbr = resolve_model_materials(options)[7]
    assert pbr.metallic_factor == 0.8
    assert pbr.roughness_factor == 0.25
    assert pbr.base_color_factor == (0.5, 0.25, 0.0, 1.0)
    assert pbr.base_color is not None and pbr.base_color.uid == "abc123"


def test_glossiness_workflow_marks_roughness_for_inversion():
    mats = parse_materials(
        options_with({"GlossinessPBR": {"enable": True, "factor": 0.75}})
    )
    pbr = to_pbr(mats[7])
    assert pbr.roughness_is_glossiness is True
    assert pbr.metallic_factor == 0.0
    # No map, so the complement is exact
    assert math.isclose(pbr.roughness_factor, 0.25)


def test_additive_opacity_is_flagged_rather_than_blended():
    mats = parse_materials(
        options_with({"Opacity": {"enable": True, "factor": 0.4, "type": "additive"}})
    )
    pbr = to_pbr(mats[7])
    assert pbr.alpha_mode == "BLEND"
    assert pbr.additive is True
    assert pbr.base_color_factor[3] == 1.0


def test_blend_opacity_folds_into_base_color_alpha():
    mats = parse_materials(options_with({"Opacity": {"enable": True, "factor": 0.4}}))
    pbr = to_pbr(mats[7])
    assert pbr.alpha_mode == "BLEND"
    assert pbr.base_color_factor[3] == 0.4


def test_opaque_alphablend_factor_one_stays_opaque():
    """Viewer treats alphaBlend+factor=1 with no map as not effective."""
    mats = parse_materials(
        options_with({"Opacity": {"enable": True, "factor": 1.0, "type": "alphaBlend"}})
    )
    pbr = to_pbr(mats[7])
    assert pbr.alpha_mode == "OPAQUE"
    assert pbr.base_color_factor[3] == 1.0


def test_tinted_clearcoat_produces_absorption():
    mats = parse_materials(
        options_with(
            {
                "ClearCoat": {
                    "enable": True,
                    "factor": 1.0,
                    "tint": [0.2, 0.4, 0.6],
                    "thickness": 5.0,
                },
                "ClearCoatRoughness": {"enable": True, "factor": 0.1},
            }
        )
    )
    pbr = to_pbr(mats[7])
    assert pbr.clearcoat_factor == 1.0
    assert pbr.coat_absorption == clearcoat_absorption((0.2, 0.4, 0.6), 5.0)
    # Darker tint absorbs more, so the transmitted red is below the blue
    assert pbr.coat_absorption[0] < pbr.coat_absorption[2]


def test_cull_face_disable_means_double_sided():
    mats = parse_materials(options_with({}, cullFace="DISABLE"))
    assert to_pbr(mats[7]).double_sided is True


def test_uv_transform_survives_the_projection():
    mats = parse_materials(
        options_with(
            {
                "AlbedoPBR": {
                    "enable": True,
                    "texture": {"uid": "abc"},
                    "UVTransforms": {"scale": [2.0, 2.0], "offset": [0.5, 0.0]},
                }
            }
        )
    )
    uv = to_pbr(mats[7]).base_color.uv
    assert uv.scale == (2.0, 2.0)
    assert uv.offset == (0.5, 0.0)
    assert uv.is_identity is False


# ---------------------------------------------------------------------------
# StateSet join
# ---------------------------------------------------------------------------

def stateset_node(unique_id: int, slot_id: int, name: str) -> dict:
    return {
        "osg.StateSet": {
            "UniqueID": unique_id,
            "Name": name,
            "UserDataContainer": {"Values": [{"Name": "UniqueID", "Value": str(slot_id)}]},
        }
    }


def test_index_statesets_keys_by_unique_id_and_keeps_the_slot():
    registry = index_statesets({"Children": [stateset_node(12, 7, "paint")]})
    assert registry[12].name == "paint"
    assert registry[12].material_slot_id == 7


def test_binder_inherits_the_parent_stateset():
    registry = index_statesets({"Children": [stateset_node(12, 7, "paint")]})
    binder = StateSetBinder(registry)

    parent = binder.for_node({"StateSet": {"osg.StateSet": {"UniqueID": 12}}}, None)
    assert parent.material is registry[12]

    # A geometry with no StateSet of its own keeps what it inherited
    assert binder.for_geometry({"Name": "mesh"}, parent).material is registry[12]


def test_binder_falls_back_to_an_exact_name_match():
    registry = index_statesets({"Children": [stateset_node(12, 7, "paint")]})
    binder = StateSetBinder({}, by_name={"lamp": registry[12]})
    assert binder.for_geometry({"Name": "lamp"}, None).material is registry[12]
    assert binder.for_geometry({"Name": "other"}, None).material is None
