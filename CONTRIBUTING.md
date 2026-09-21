# Contributing
1. Keep the invariant: LLM writes plan JSON only, geometry is computed by code.
2. Every new executor must add a verifier case in `tests/` with 1/1000 bbox tolerance.
3. Rust core (`crates/cadcraft-geom`) must stay `no_std`-friendly for WASM; Python works without it.
4. Run `pytest -q` + `cargo test -p cadcraft-geom` before PR.
