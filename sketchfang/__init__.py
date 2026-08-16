"""
SketchFang — educational Sketchfab viewer research pipeline.

EDUCATIONAL USE ONLY. Not for redistributing models you do not own or have
permission to copy. Comply with Sketchfab ToS, copyright, and model licenses.

Layers, lowest first (a layer never imports one above it):

    util        stdlib helpers: logging, uid parsing, 4x4 math, padding
    api         Sketchfab HTTP endpoints (metadata / textures / options)
    crypto      BINZ decryption (session VM + xorshift16 + r4Cz/Zstd)
    osgjs       OSGJS buffer codecs, transforms, scene walk, geometry decode
    textures    texture listing, download, viewer `pk` unscramble
    materials   server material table -> StateSet join -> baked glTF slots
    gltf        GLB writer and reader
    pipeline    end-to-end orchestration
    cli         argument parsing only

``pipeline.rip_model`` is the single entry point for the full flow.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__", "rip_model"]


def __getattr__(name: str):
    # Imported lazily so `import sketchfang` stays cheap and dependency-free.
    if name == "rip_model":
        from .pipeline import rip_model

        return rip_model
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
