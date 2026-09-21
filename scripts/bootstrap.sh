#!/bin/bash
set -e
python3 -m pip install -e ".[dev]" || pip install -e ".[dev]"
echo "need: ollama pull qwen3:4b ; optional: TYPESAFE_API_KEY for --with-jev"
