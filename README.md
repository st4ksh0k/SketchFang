# SketchFang

**Educational research pipeline.**  
The education is *how your DRM works, babe.*

SketchFang is a pure-Python lab for taking Sketchfab’s browser viewer apart with tweezers: BINZ wrapping, session bytecode, xorshift16, r4Cz/Zstd, OSGJS codecs, `pk` texture scramble, and a glTF/GLB on the other side. No WASM oracle. No “please use our download button.” Just the path the viewer already walks — written down so you can read it.

We promote **SketchFang**, not Sketchfab. They’re welcome to keep rotating hex keys in minified JS. I’ll keep a watcher.

---

## What this is (and isn’t)

| This is | This isn’t |
| --- | --- |
| A study of client-side “protection” that ships to every browser | A Sketchfab feature request |
| A clean layer cake you can unit-test offline | A SaaS, a scraper farm, or a Discord bot |
| Proof that “encrypted on the wire” ≠ “secret” | Legal advice (you already knew that) |

**Responsible adult voice (one paragraph, then we move on):** copyright and ToS still exist in meatspace. If you don’t have rights to a model, don’t be weird with it. SketchFang is for learning the pipeline — preferably on assets you’re allowed to poke. Misuse is on you; the fangs were always decorative.

---

## Layout

```
SketchFang/
├── sketchfang/
│   ├── pipeline.py        # metadata → decrypt → textures → materials → .glb
│   ├── cli/               # argument parsing only
│   ├── api/               # /i/models/{uid} · /textures · /options
│   ├── crypto/            # BINZ decryptor (pure Python, no WASM cosplay)
│   ├── osgjs/             # buffers · codecs · transforms · walk · geometry
│   ├── textures/          # listing · download · viewer pk unscramble
│   ├── materials/         # server channels → PBR → StateSet join → bake
│   ├── gltf/              # GLB writer / reader
│   └── util/
├── scripts/
│   ├── extraction_pipeline.py  # shim → sketchfang.cli.rip
│   ├── binz_decrypt.py         # shim → sketchfang.cli.decrypt
│   ├── binz_probe.py           # protection / r4Cz framing probe
│   ├── watch_static_key.py     # catch their key rotation mid-flex
│   └── launchd/                # optional macOS schedule for the watcher
└── tests/                      # the parts that don’t need their CDN
```

Layers only import upward. OSGJS codecs and the `pk` unscrambler run with the network unplugged — as nature intended.

### Pipeline (the tour)

1. Fetch metadata (`/i/models/{uid}`) — they hand you the map
2. Pull `file.binz` / `model_file.binz` — still “protected,” sure
3. Decrypt in pure Python: unwrap `protection.b` → session VM + xorshift16 → r4Cz → Zstd → OSGJS
4. Decode OSGJS compressed buffers (strips, watermarks, the whole costume party)
5. Download textures; unscramble with the viewer’s own `pk` 8×8 tile map
6. Join materials via StateSet `UniqueID` (not filename astrology)
7. Emit glTF 2.0 `.glb` — Z-up fixed, false `BLEND` left at the door

---

## Requirements

- Python 3.10+
- `requests`, `pillow`, `zstandard` (see `requirements.txt`)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .
```

That puts `sketchfang`, `sketchfang-decrypt`, `sketchfang-inspect`, and
`sketchfang-unscramble` on your PATH. Or just `python3 -m sketchfang` from the repo root — fewer ceremonies.

---

## Usage

```bash
# Full pipeline → GLB
python3 -m sketchfang <model-url-or-uid> -o ./out

# Geometry only (skip the texture shopping trip)
python3 -m sketchfang <model-url-or-uid> --no-textures -o ./out

# Offline: you already have the organs
python3 -m sketchfang <uid> --osgjs path/to/file.osgjs --model-bin path/to/model.bin -o ./out
```

Decrypt-only:

```bash
python3 -m sketchfang.cli.decrypt <uid-or-url> -o out.osgjs
python3 -m sketchfang.cli.decrypt --raw file.binz --key <protection.b> -o out.osgjs
```

Inspect a rip, or undo one scrambled texture by hand:

```bash
python3 -m sketchfang.cli.inspect ./out/model.glb
python3 -m sketchfang.cli.unscramble texture.png <pk> --flip-y -o decoded.png
```

Shims in `scripts/` exist for muscle memory.

---

## Development

```bash
pip install -e ".[dev]"
pytest
```

Tests cover the offline spine: OSGJS codecs, `pk` unscramble, material projection, crypto helpers, and a walk → decode → GLB → read round trip on an inline scene. No API key. No “enterprise plan.”

### Viewer static key

They park a 40-char hex key in the viewer bundle and rotate it like that changes the homework. SketchFang tries known keys, then scrapes the live one from embed JS (in memory — we don’t keep their laundry), patches `sketchfang/crypto/protection.py`, and retries.

Optional watchdog (local commit, no push unless you ask for trouble):

```bash
python3 scripts/watch_static_key.py --check-only
python3 scripts/watch_static_key.py --commit
```

macOS launchd every 6 hours:

```bash
cp scripts/launchd/com.sketchfang.watch-static-key.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.sketchfang.watch-static-key.plist
```

Logs: `/tmp/sketchfang-watch-static-key.log`.

---

## Status

Side project. Viewer builds move; keys move; we move faster with fewer product managers.

---

## License / vibes

No warranty. As-is. For education, research, and people who read JavaScript for sport.

Respect creators. Mock platforms. If those two conflict, you already know which side SketchFang was named for.
