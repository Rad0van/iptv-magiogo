#!/bin/bash
# Optional: patch Kodi's Estuary skin so the add-on's locked content gets a red
# indicator across views — a red PADLOCK on locked playable items and a red
# FOLDER on fully-locked folders:
#   * list views (List/WideList): the row glyph becomes the red folder/padlock
#   * poster/wall views (Poster/Wall/InfoWall): a red badge in the poster corner
#
# Why this is needed: Estuary's views draw a fixed glyph / the poster and ignore
# an add-on's ListItem.Icon, and Kodi's built-in "locked" overlay is overwritten
# by the watched-state thumb-loader. The ONLY lock signal that survives and is
# readable by the skin is a ListItem property, which the add-on sets
# (ParentalLocked). This installs a *user-space* copy of Estuary (which overrides
# the bundled one) that renders our red textures for that property.
#
# Usage:   bash scripts/patch_estuary_lock.sh   # then restart Kodi
# Re-run after a Kodi update (a newer *bundled* Estuary would otherwise win).
# Remove:  delete ~/.kodi/addons/skin.estuary and restart Kodi.
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

# 1) list views: the row glyph (ListWatchedIconVar) + a shared LockBadgeVar
python3 - "$DST/xml/Variables.xml" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "ParentalLocked" in s and "LockBadgeVar" in s:
    print("Variables.xml already patched"); sys.exit(0)
anchor = '<variable name="ListWatchedIconVar">'
if anchor not in s:
    sys.exit("ListWatchedIconVar not found — skin layout changed; update this script.")
# red folder for fully-locked folders, red padlock for locked items
rows = ('\n\t\t<value condition="ListItem.Property(ParentalLocked) + ListItem.IsFolder">folder_red.png</value>'
        '\n\t\t<value condition="ListItem.Property(ParentalLocked)">lock_red.png</value>')
s = s.replace(anchor, anchor + rows, 1)
# shared variable for the poster-corner badge texture
badge = ('\t<variable name="LockBadgeVar">\n'
         '\t\t<value condition="ListItem.IsFolder">folder_red.png</value>\n'
         '\t\t<value>lock_red.png</value>\n'
         '\t</variable>\n')
s = s.replace('\t' + anchor, badge + '\t' + anchor, 1)
open(p, "w", encoding="utf-8").write(s)
print("patched Variables.xml (ListWatchedIconVar + LockBadgeVar)")
PY

# 2) poster/wall views: a corner badge on the shared poster/episode layouts
#    (InfoWallMovieLayout + InfoWallEpisodeLayout are reused by Poster/Wall/InfoWall)
python3 - "$DST/xml/View_54_InfoWall.xml" <<'PY'
import sys
p = sys.argv[1]
s = open(p, encoding="utf-8").read()
if "LockBadgeVar" in s:
    print("View_54_InfoWall.xml already patched"); sys.exit(0)

def badge(left, top, size):
    return (f'\t\t\t<control type="image">\n'
            f'\t\t\t\t<left>{left}</left>\n'
            f'\t\t\t\t<top>{top}</top>\n'
            f'\t\t\t\t<width>{size}</width>\n'
            f'\t\t\t\t<height>{size}</height>\n'
            f'\t\t\t\t<aspectratio>keep</aspectratio>\n'
            f'\t\t\t\t<texture>$VAR[LockBadgeVar]</texture>\n'
            f'\t\t\t\t<visible>ListItem.Property(ParentalLocked)</visible>\n'
            f'\t\t\t</control>\n')

def insert(s, include_name, ctrl):
    i = s.index(f'<include name="{include_name}">')
    j = s.index('</definition>', i)
    return s[:j] + ctrl + s[j:]

# poster top-right corner (poster box is ~left 15..305, top -10..405)
s = insert(s, "InfoWallMovieLayout", badge(250, -4, 54))
# episode thumb top-right corner (thumb is ~316 wide)
s = insert(s, "InfoWallEpisodeLayout", badge(262, 14, 48))
open(p, "w", encoding="utf-8").write(s)
print("patched View_54_InfoWall.xml (Poster/Wall/InfoWall poster + episode badges)")
PY

echo "Done. Restart Kodi to load the patched skin."
