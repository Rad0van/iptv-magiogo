"""Native Live TV/EPG integration via pvr.iptvsimple.

Writes an M3U (channels playing through ``plugin://`` callbacks) and an XMLTV
guide into the add-on profile, and points pvr.iptvsimple's *instance* settings
at those local files.

Important: we deliberately never enable/disable the PVR add-on to force a
reload — doing that while Kodi is starting/running makes pvr.iptvsimple abort
(SIGABRT in CPVRClients::UpdateClients). Configuration changes are written to
the instance-settings file and take effect on the next Kodi restart. On Kodi 20+
the active config lives in ``instance-settings-*.xml`` (not the add-on-level
``settings.xml``), so we edit that.
"""

import glob
import os
import xml.etree.ElementTree as ET

import xbmcaddon
import xbmcgui
import xbmcvfs

from core import build_kodi_playlist, build_epg, MagioError

from .context import ADDON, ADDON_ID, client, log, notify, profile_dir, setting_int

IPTV_SIMPLE = "pvr.iptvsimple"
PLAYLIST_FILE = "playlist.m3u"
EPG_FILE = "epg.xml"

# pvr.iptvsimple settings to point it at our local files.
_DESIRED = {
    "m3uPathType": "0",  # 0 = Local path
    "m3uUrl": "",
    "epgPathType": "0",
    "epgUrl": "",
}


def paths():
    d = profile_dir()
    return os.path.join(d, PLAYLIST_FILE), os.path.join(d, EPG_FILE)


def files_exist():
    m3u_path, epg_path = paths()
    return os.path.exists(m3u_path) and os.path.exists(epg_path)


def generate(epg=True, force_epg=False):
    """Write playlist.m3u (always) and epg.xml (when ``epg``) into the profile.

    Returns (m3u_path, epg_path). EPG is cached for 7 days by ``build_epg``;
    ``force_epg`` removes the cache to force a rebuild.
    """
    c = client()
    m3u_path, epg_path = paths()

    m3u = build_kodi_playlist(c, f"plugin://{ADDON_ID}/")
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write(m3u)
    log(f"wrote playlist: {m3u_path}")

    if epg:
        if force_epg and os.path.exists(epg_path):
            os.remove(epg_path)
        build_epg(c, epg_path, days_forward=setting_int("epg_days", 5))
        log(f"wrote epg: {epg_path}")

    return m3u_path, epg_path


def _iptvsimple_data_dir():
    return xbmcvfs.translatePath(
        f"special://userdata/addon_data/{IPTV_SIMPLE}/"
    )


def configure_iptvsimple(m3u_path, epg_path):
    """Point pvr.iptvsimple at our local files via its instance settings.

    Returns True if at least one settings file was updated. Never toggles the
    add-on; the change applies on the next Kodi restart.
    """
    desired = dict(_DESIRED, m3uPath=m3u_path, epgPath=epg_path)
    updated = False

    for path in glob.glob(
        os.path.join(_iptvsimple_data_dir(), "instance-settings-*.xml")
    ):
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            for setting in root.findall("setting"):
                sid = setting.get("id")
                if sid in desired:
                    setting.text = desired[sid]
                    setting.attrib.pop("default", None)  # mark as user-set
            tree.write(path, encoding="utf-8", xml_declaration=True)
            updated = True
            log(f"configured iptvsimple instance: {path}")
        except Exception as e:  # keep going; fall back to add-on-level below
            log(f"instance settings write failed ({path}): {e}")

    # Add-on-level fallback (covers a fresh single-config install with no instance).
    try:
        ipa = xbmcaddon.Addon(IPTV_SIMPLE)
        for key, value in desired.items():
            ipa.setSetting(key, value)
    except Exception as e:
        log(f"add-on-level iptvsimple settings failed: {e}")

    return updated


def setup(interactive=False):
    """Generate the playlist + EPG and point pvr.iptvsimple at them.

    Used by the 'Set up Live TV' menu action. Does NOT reload the PVR client
    (that crashes Kodi); the user restarts Kodi to load the channels.
    """
    progress = None
    if interactive:
        progress = xbmcgui.DialogProgress()
        progress.create("Magio GO", "Building channel list and guide…")
    try:
        m3u_path, epg_path = generate(epg=True)
    except MagioError:
        if progress:
            progress.close()
        notify("Live TV setup failed — check your username/password in settings")
        return False
    except Exception as e:
        log(f"setup generate failed: {e}")
        if progress:
            progress.close()
        notify(f"Live TV setup failed: {e}")
        return False

    if progress:
        progress.update(80, "Configuring PVR IPTV Simple Client…")
    configured = configure_iptvsimple(m3u_path, epg_path)
    ADDON.setSetting("enable_livetv", "true")  # service keeps the guide fresh
    if progress:
        progress.close()

    if interactive:
        if configured:
            xbmcgui.Dialog().ok(
                "Magio GO",
                "Live TV is ready and PVR IPTV Simple Client has been pointed "
                "at the generated channel list and guide.\n\n"
                "Restart Kodi to load the channels (then see the TV section).",
            )
        else:
            xbmcgui.Dialog().ok(
                "Magio GO",
                "Channel list and guide were generated, but the PVR client "
                "could not be configured automatically. In PVR IPTV Simple "
                "Client settings set, then restart Kodi:\n\n"
                f"M3U local path:\n{m3u_path}\n\nEPG local path:\n{epg_path}",
            )
    return True
