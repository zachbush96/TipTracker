#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

# Install locked dependencies into the existing Replit Python environment.
# Do not create a separate environment or remove unrelated installed packages.
requirements="$(mktemp)"
trap 'rm -f "$requirements"' EXIT
uv export --locked --no-dev --no-emit-project --format requirements-txt --output-file "$requirements" >/dev/null
uv pip install --python "$(command -v python)" --require-hashes -r "$requirements"

# Check source syntax without importing the app or touching saved data.
python - <<'PY'
import ast
from pathlib import Path

for path in Path(".").glob("*.py"):
    ast.parse(path.read_text(), filename=str(path))
print("Post-merge dependency and syntax checks passed.")
PY
