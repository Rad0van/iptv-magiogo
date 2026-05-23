#!/bin/bash
# Build a personal Kodi repository so the add-on auto-updates.
#
# Usage:  bash scripts/build_repo.sh [BASE_URL]
#   BASE_URL is where you will host the contents of dist/ (e.g. a GitHub Pages
#   URL like https://USER.github.io/iptv-magiogo). It is baked into the
#   repository add-on so Kodi knows where to fetch updates.
#
# Output (dist/) — upload its contents to BASE_URL:
#   dist/addons.xml, dist/addons.xml.md5
#   dist/plugin.video.magiogo/plugin.video.magiogo-<ver>.zip (+ icon/fanart)
#   dist/repository.magiogo/repository.magiogo-<ver>.zip      (+ icon)
# Install repository.magiogo once from zip; the plugin then updates from BASE_URL.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BASE_URL="${1:-https://YOUR-HOST.example/iptv-magiogo}"
BASE_URL="${BASE_URL%/}"
DIST="$ROOT/dist"
PY="$ROOT/.venv/bin/python"

# 1) build the plugin zip (syncs core + vendors deps)
bash "$ROOT/scripts/build_addon.sh" >/dev/null

# 2) render the repository add-on with the chosen base URL
TMP="$(mktemp -d)"
mkdir -p "$TMP/repository.magiogo"
sed "s#@BASEURL@#${BASE_URL}#g" "$ROOT/addon/repository.magiogo/addon.xml.in" \
    > "$TMP/repository.magiogo/addon.xml"
cp "$ROOT/addon/repository.magiogo/icon.png" "$TMP/repository.magiogo/icon.png"

PVER="$($PY -c "import xml.etree.ElementTree as ET;print(ET.parse('$ROOT/addon/plugin.video.magiogo/addon.xml').getroot().get('version'))")"
RVER="$($PY -c "import xml.etree.ElementTree as ET;print(ET.parse('$TMP/repository.magiogo/addon.xml').getroot().get('version'))")"

# 3) lay out dist/
rm -rf "$DIST"
mkdir -p "$DIST/plugin.video.magiogo" "$DIST/repository.magiogo"
cp "$ROOT/addon/plugin.video.magiogo.zip" "$DIST/plugin.video.magiogo/plugin.video.magiogo-$PVER.zip"
cp "$ROOT/addon/plugin.video.magiogo/resources/icon.png" "$DIST/plugin.video.magiogo/icon.png"
cp "$ROOT/addon/plugin.video.magiogo/resources/fanart.jpg" "$DIST/plugin.video.magiogo/fanart.jpg"
( cd "$TMP" && zip -r -q "$DIST/repository.magiogo/repository.magiogo-$RVER.zip" repository.magiogo )
cp "$TMP/repository.magiogo/icon.png" "$DIST/repository.magiogo/icon.png"

# 4) addons.xml (union of the two add-on manifests) + md5
"$PY" - "$ROOT/addon/plugin.video.magiogo/addon.xml" "$TMP/repository.magiogo/addon.xml" "$DIST/addons.xml" <<'P'
import sys
out = ['<?xml version="1.0" encoding="UTF-8"?>', '<addons>']
for f in sys.argv[1:-1]:
    s = open(f, encoding="utf-8").read()
    out.append(s[s.index("<addon "):].strip())
out.append('</addons>')
open(sys.argv[-1], "w", encoding="utf-8").write("\n".join(out) + "\n")
P
"$PY" - "$DIST/addons.xml" "$DIST/addons.xml.md5" <<'P'
import sys, hashlib
open(sys.argv[2], "w").write(hashlib.md5(open(sys.argv[1], "rb").read()).hexdigest())
P

rm -rf "$TMP"
echo "repo built in $DIST"
echo "  plugin   v$PVER"
echo "  repo     v$RVER  (base url: $BASE_URL)"
echo "Host the contents of dist/ at that URL, then install repository.magiogo-$RVER.zip in Kodi."
