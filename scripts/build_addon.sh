#!/bin/bash
# Sync the shared core into the add-on and build an installable zip.
#
# The `core` package is the single source of truth in src/core; it is copied
# into the add-on's resources/lib at build time (kept out of git). xmltv and
# roman are pure-python single-file deps not packaged for Kodi, so they are
# vendored too. requests comes from script.module.requests at runtime.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADDON="$ROOT/addon/plugin.video.magiogo"
LIB="$ADDON/resources/lib"

# 1) shared core
rm -rf "$LIB/core"
cp -r "$ROOT/src/core" "$LIB/core"

# 2) vendored single-file deps
for mod in xmltv roman; do
    src="$(find "$ROOT/.venv" -name "$mod.py" -path '*site-packages*' 2>/dev/null | head -1)"
    if [ -n "$src" ]; then
        cp "$src" "$LIB/$mod.py"
    else
        echo "WARNING: $mod.py not found in .venv (run pip install -r requirements.txt)"
    fi
done

# 3) tidy
find "$LIB" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
echo "core + deps synced into $LIB"

# 4) zip
cd "$ROOT/addon"
rm -f plugin.video.magiogo.zip
zip -r -q plugin.video.magiogo.zip plugin.video.magiogo -x '*/__pycache__/*' '*.pyc'
echo "built: $ROOT/addon/plugin.video.magiogo.zip"
