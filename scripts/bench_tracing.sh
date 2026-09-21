#!/bin/bash
set -e
for f in synth_rect level2_bracket level3_floor; do
  echo "===== $f ====="
  PYTHONPATH=src /opt/homebrew/opt/python@3.12/bin/python3.12 examples/trace_image.py --image tests/testdata/$f.png --out /tmp/${f}.dxf --preview /tmp/${f}_preview.png 2>&1 | head -n 25
done
