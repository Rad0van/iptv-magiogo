"""Native Live TV/EPG integration via pvr.iptvsimple.

The add-on writes an M3U (channels playing through ``plugin://`` callbacks) and
an XMLTV guide into its profile dir, then points pvr.iptvsimple at those files
and reloads it. The M3U's plugin URLs mean tokens are refreshed per play, so the
files only need periodic regeneration (handled by the service for EPG freshness).
"""

import json
import os

import xbmc
import xbmcaddon
import xbmcgui

from core import build_kodi_playlist, build_epg

from .context import ADDON, ADDON_ID, client, log, notify, profile_dir, setting_int

IPTV_SIMPLE = "pvr.iptvsimple"
PLAYLIST_FILE = "playlist.m3u"
EPG_FILE = "epg.xml"


def paths():
    d = profile_dir()
    return os.path.join(d, PLAYLIST_FILE), os.path.join(d, EPG_FILE)


def _jsonrpc(method, params):
    return xbmc.executeJSONRPC(json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ))


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
        days = setting_int("epg_days", 5)
        build_epg(c, epg_path, days_forward=days)
        log(f"wrote epg: {epg_path}")

    return m3u_path, epg_path


def configure_iptvsimple(m3u_path, epg_path):
    """Point pvr.iptvsimple at our local files and enable catchup. Returns bool."""
    try:
        ipa = xbmcaddon.Addon(IPTV_SIMPLE)
    except Exception:
        log("pvr.iptvsimple not installed")
        return False
    try:
        ipa.setSetting("m3uPathType", "0")  # 0 = Local path
        ipa.setSetting("m3uPath", m3u_path)
        ipa.setSetting("epgPathType", "0")
        ipa.setSetting("epgPath", epg_path)
        ipa.setSetting("catchupEnabled", "true")
        ipa.setSetting("logoPathType", "1")  # logos from M3U/EPG urls
        return True
    except Exception as e:
        log(f"configure_iptvsimple error: {e}")
        return False


def reload_iptvsimple():
    """Toggle pvr.iptvsimple off/on so it re-reads the playlist/EPG."""
    _jsonrpc("Addons.SetAddonEnabled", {"addonid": IPTV_SIMPLE, "enabled": False})
    xbmc.sleep(1500)
    _jsonrpc("Addons.SetAddonEnabled", {"addonid": IPTV_SIMPLE, "enabled": True})


def setup(interactive=False):
    """One-shot: generate files, configure pvr.iptvsimple, reload.

    Used by the 'Set up Live TV' menu action and by the service on first run.
    """
    progress = None
    if interactive:
        progress = xbmcgui.DialogProgress()
        progress.create("Magio GO", "Setting up Live TV…")
        progress.update(10, "Building channel list and guide…")
    try:
        m3u_path, epg_path = generate(epg=True)
    except Exception as e:
        log(f"setup generate failed: {e}")
        if progress:
            progress.close()
        notify("Live TV setup failed — check credentials")
        return False

    if progress:
        progress.update(80, "Configuring PVR IPTV Simple Client…")
    if not configure_iptvsimple(m3u_path, epg_path):
        if progress:
            progress.close()
        notify("Install 'PVR IPTV Simple Client', then retry")
        return False

    reload_iptvsimple()
    # keep the background service refreshing the guide from now on
    ADDON.setSetting("enable_livetv", "true")
    if progress:
        progress.update(100, "Done")
        progress.close()
    notify("Live TV is set up — open the TV section")
    return True
