#!/bin/bash
set -e
TEXT=${1:-"画80x50矩形，中心Φ20孔"}
OUT=${2:-/tmp/cadcraft_out.dxf}
python -m cadcraft "$TEXT" -o "$OUT" --verify
echo "dxf=$OUT report=report.json"
