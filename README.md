# CadCraft

CadCraft is a local-first kit for commanding CAD with small models (0.5B–4B).

It turns natural language and raster images into dimension-correct CAD (DXF first, STEP/FreeCAD/AutoCAD next) with a `Plan-Then-Construct + Verify` loop: a small local LLM only writes a symbolic dimension-aware plan (JSON), deterministic Python/Rust code does the exact geometry, and a judge (local tolerance checks + optional Jev Score/Choice) closes the loop.

> Inspired by `Pointer-CAD v2 (ECCV 2026)` — decouple parameter reasoning from geometric construction — and `TypeSafe Jev (System One Models)` — use cheap, fast, calibrated judgments for every step instead of one giant generation.

## Why this exists

General LLMs (even GPT-5.2 / Gemini 3 Pro class) draw “look-alike” CAD but fail metric scale: a `0.7cm` height becomes `0.67`, IoU still `0.96`, yet the part is scrap. Pointer-CAD v2 showed a 1.5B purpose-built model beating general giants by 21%+ on vertex/edge/face accuracy by:

1. planning with explicit units/symbols (`<L1=80mm>`, `<L3=2*L2>`) before building,
2. referencing parameters via pointer instead of quantized prediction,
3. evaluating without normalization at 1/1000 bbox tolerance.

CadCraft is the engineering port of that lesson: **small model as foreman, CAD kernel as hands, judge as inspector.**

## Highlights (MVP roadmap)

- [x] `文本出DXF`: text → JSON plan → `ezdxf` → tolerance check → auto-repair (3 rounds)
- [ ] `Jev裁判`: `Score` for dimensional acceptance, `Choice` for entity classification, `Noul` for done/repair routing + context compaction
- [ ] `图片描图`: OpenCV/LSD + vectorize + OCR dimensions + LLM semantic stitching → DXF
- [ ] `AutoCAD/FreeCAD联调`: same plan drives `pyautocad` / FreeCAD headless / CadQuery / Build123d

See [docs/product-plan.md](docs/product-plan.md) and [docs/architecture.md](docs/architecture.md).

## Quickstart (Python + Ollama)

```bash
cd ~/work/github/cadcraft-dev/cadcraft
./scripts/bootstrap.sh
# pull a small coder, e.g. qwen3:4b / qwen2.5-coder:3b
ollama pull qwen3:4b

# 1) text -> plan -> dxf -> verify
python -m cadcraft "画80x50矩形，中心Φ20孔" -o out.dxf --verify

# 2) run the bundled example
python examples/text_to_dxf.py --text "100x60矩形，左下角R5圆角" --out /tmp/demo.dxf

# 3) with Jev as judge (needs TYPESAFE_API_KEY)
export TYPESAFE_API_KEY=...
python examples/jev_verify.py --dxf /tmp/demo.dxf
```

Outputs are deterministic DXF R2010 + PNG preview + `report.json` with vertex/edge-style tolerance results.

## Layout

```
src/cadcraft/
  planner/    Ollama/JSON-schema planner (System 2, slow) — never outputs coordinates directly
  executor/   ezdxf / FreeCAD / AutoCAD drivers (deterministic hands)
  verifier/   local tolerance checks + Jev client (System 1, fast judge)
  tracing/    raster -> vector + OCR -> semantic stitch (WIP)
crates/cadcraft-geom/  Rust core: tolerance, bbox, segment math (WASM-ready)
wasm/         wasm-pack output placeholder (mirrors markcraft build flow)
docs/         product plan, Pointer-CAD v2 notes, Jev notes, architecture
examples/     runnable MVP scripts
tests/        pytest: schema, tolerance, pipeline
reference/    upstream papers/links, company templates (git-ignored if private)
```

## Local-first & privacy

Drawings stay local by default. Only `verifier/jev_judge.py` calls the cloud, and only when you export the key + pass `--with-jev`. No drawing bytes are sent without that flag. See [SECURITY.md](SECURITY.md).

## Development

```bash
pip install -e ".[dev]"
pytest -q
cargo test -p cadcraft-geom
```

Rust/WASM mirrors `markcraft-dev/markcraft`: `cargo` core → `wasm-pack` → `wasm/` → Python via `wasmtime` (optional). Python works without Rust; Rust only accelerates tolerance/bbox checks.

## Documentation

- [中文文档](README_zh.md)
- [Product plan](docs/product-plan.md)
- [Architecture](docs/architecture.md)
- [Pointer-CAD v2 notes](docs/pointer-cad-v2-notes.md)
- [Jev notes](docs/jev-notes.md)

## License

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Tinker Agora.
Remote: `https://github.com/tinkeragora/cadcraft` (local grouping dir `cadcraft-dev/cadcraft` mirrors `markcraft-dev/markcraft`).
