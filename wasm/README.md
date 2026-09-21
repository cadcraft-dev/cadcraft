# wasm
Build output for `cadcraft-geom` (mirrors markcraft `pnpm run build:wasm`).
```bash
wasm-pack build crates/cadcraft-geom --target web --out-dir wasm/pkg
```
Python can optionally load it via wasmtime; pure-Python fallback always works.
