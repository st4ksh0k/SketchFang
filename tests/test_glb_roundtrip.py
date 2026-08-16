"""Walk → decode → write → read, with an inline OSGJS scene (no network)."""

from __future__ import annotations

from sketchfang.gltf.reader import Glb
from sketchfang.gltf.writer import write_glb
from sketchfang.osgjs.geometry import decode_geometry
from sketchfang.osgjs.walk import walk_geometries
from sketchfang.util.matrix import Z_UP_TO_Y_UP, transform_point

TRIANGLE_SCENE = {
    "osg.Node": {
        "Children": [
            {
                "osg.Geometry": {
                    "Name": "triangle",
                    "VertexAttributeList": {
                        "Vertex": {
                            "ItemSize": 3,
                            "Array": {
                                "Float32Array": {
                                    "Size": 3,
                                    "Elements": [0, 0, 0, 1, 0, 0, 0, 1, 0],
                                }
                            },
                        }
                    },
                    "PrimitiveSetList": [
                        {
                            "DrawElementsUShort": {
                                "Mode": "TRIANGLES",
                                "Indices": {
                                    "ItemSize": 1,
                                    "Array": {
                                        "Uint16Array": {"Size": 3, "Elements": [0, 1, 2]}
                                    },
                                },
                            }
                        }
                    ],
                }
            }
        ]
    }
}


def test_walk_finds_geometry_without_a_material_binder():
    found: list = []
    walk_geometries(TRIANGLE_SCENE, found)
    assert len(found) == 1
    geom, world, binding = found[0]
    assert geom["Name"] == "triangle"
    assert world[0] == 1.0
    assert binding is None


def test_decoded_triangle_round_trips_through_a_glb(tmp_path):
    found: list = []
    walk_geometries(TRIANGLE_SCENE, found)
    meshes = [decode_geometry(g, {}, world, binding) for g, world, binding in found]

    out = tmp_path / "triangle.glb"
    write_glb(meshes, {}, out, progress=False)

    glb = Glb(out)
    assert glb.json["asset"]["version"] == "2.0"
    assert len(glb.json["meshes"]) == 1
    # Mesh nodes hang under a SketchfabRoot that does Z-up → Y-up
    root = glb.json["nodes"][glb.json["scenes"][0]["nodes"][0]]
    assert root["name"] == "SketchfabRoot"
    assert root["matrix"] == Z_UP_TO_Y_UP
    mesh_node = glb.json["nodes"][root["children"][0]]
    assert mesh_node["name"] == "triangle"
    # Untextured meshes get the grey fallback, never a random texture
    assert "images" not in glb.json
    assert glb.json["materials"][0]["name"] == "default"

    prim = glb.json["meshes"][0]["primitives"][0]
    assert glb.accessor(prim["attributes"]["POSITION"]) == [0, 0, 0, 1, 0, 0, 0, 1, 0]
    assert glb.accessor(prim["indices"]) == [0, 1, 2]
    # Local (0,1,0)_osg becomes (0,0,-1)_gltf under the root
    wm = glb.world_matrices()[root["children"][0]]
    assert transform_point(wm, (0.0, 1.0, 0.0)) == (0.0, 0.0, -1.0)
