#!/bin/bash
# Optional: patch Kodi's Estuary skin so the add-on's locked items get a red
# indicator in list views — a red PADLOCK on locked playable items and a red
# FOLDER on fully-locked folders.
#
# Why this is needed: Estuary's list views draw the row glyph from a fixed skin
# texture (overlays/folder.png) and ignore an add-on's ListItem.Icon; the
# built-in "locked" overlay is overwritten by Kodi's watched-state thumb-loader.
# The ONLY thing that survives and is readable by the skin is a ListItem
# property, which the add-on sets (ParentalLocked). This installs a *user-space*
# copy of Estuary (which overrides the bundled one) whose ListWatchedIconVar
# renders our red textures for that property.
#
# Usage:   bash scripts/patch_estuary_lock.sh
#   Then restart Kodi.
# Re-run after a Kodi update (a newer *bundled* Estuary would otherwise win).
# Remove:  delete ~/.kodi/addons/skin.estuary and restart Kodi (the bundled
#          skin takes over again).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RES="$ROOT/addon/plugin.video.magiogo/resources"
USERADDONS="${KODI_HOME:-$HOME/.kodi}/addons"

# locate the bundled Estuary
SYS=""
for d in /usr/share/kodi/addons/skin.estuary /usr/lib/kodi/addons/skin.estuary \
         /usr/lib/*/kodi/addons/skin.estuary /app/share/kodi/addons/skin.estuary \
         /Applications/Kodi.app/Contents/Resources/Kodi/addons/skin.estuary; do
    [ -f "$d/addon.xml" ] && { SYS="$d"; break; }
done
[ -n "$SYS" ] || { echo "Could not find the bundled skin.estuary." >&2; exit 1; }

DST="$USERADDONS/skin.estuary"
echo "Bundled Estuary: $SYS"
echo "User copy:       $DST"

# fresh copy each run, so re-running cleanly re-applies over any updated bundle
rm -rf "$DST"
mkdir -p "$USERADDONS"
cp -r "$SYS" "$DST"

# bump the user copy one patch level above the bundled one so Kodi prefers it
python3 - "$DST/addon.xml" <<'PY'
import re, sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
m = re.search(r'(id="skin\.estuary" version=")([0-9]+(?:\.[0-9]+)*)(")', s)
parts = m.group(2).split(".")
parts[-1] = str(int(parts[-1]) + 1)
ver = ".".join(parts)
s = s[:m.start()] + m.group(1) + ver + m.group(3) + s[m.end():]
open(p, "w", encoding="utf-8").write(s)
print("user skin version:", ver)
PY

# red textures (reused from the add-on's resources)
cp "$RES/lock_red.png" "$DST/media/lock_red.png"
cp "$RES/folder_red.png" "$DST/media/folder_red.png"

# prepend the locked conditions to the list-row icon variable
python3 - "$DST/xml/Variables.xml" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
anchor = '<variable name="ListWatchedIconVar">'
ins = ('\n\t\t<value condition="ListItem.Property(ParentalLocked) + ListItem.IsFolder">folder_red.png</value>'
       '\n\t\t<value condition="ListItem.Property(ParentalLocked)">lock_red.png</value>')
if anchor not in s:
    sys.exit("ListWatchedIconVar not found — skin layout changed; update this script.")
if "lock_red.png" in s:
    print("already patched"); sys.exit(0)
open(p, "w", encoding="utf-8").write(s.replace(anchor, anchor + ins, 1))
print("patched ListWatchedIconVar (folder -> red folder, item -> red padlock)")
PY

echo "Done. Restart Kodi to load the patched skin."
