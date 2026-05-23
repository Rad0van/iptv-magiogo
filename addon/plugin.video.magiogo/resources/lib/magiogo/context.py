"""Shared add-on context: the Addon handle, config, clients, paths, logging.

Imported by both the plugin router (per-invocation) and the background service,
so it must NOT touch ``sys.argv`` (which only exists for plugin invocations).
"""

import os

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from core import Config, MagioClient, VodClient, Backstage

ADDON = xbmcaddon.Addon()
ADDON_ID = ADDON.getAddonInfo("id")


def log(msg):
    xbmc.log(f"[{ADDON_ID}] {msg}", xbmc.LOGINFO)


def notify(msg):
    xbmcgui.Dialog().notification("Magio GO", str(msg), xbmcgui.NOTIFICATION_INFO, 5000)


def setting(key):
    return ADDON.getSetting(key)


def has_credentials():
    return bool(ADDON.getSetting("username") and ADDON.getSetting("password"))


def open_settings():
    ADDON.openSettings()


def setting_bool(key):
    return ADDON.getSetting(key) == "true"


def setting_int(key, default):
    try:
        return int(ADDON.getSetting(key))
    except (ValueError, TypeError):
        return default


def profile_dir():
    path = xbmcvfs.translatePath(ADDON.getAddonInfo("profile"))
    if not xbmcvfs.exists(path):
        xbmcvfs.mkdirs(path)
    return path


def make_config():
    return Config(
        username=ADDON.getSetting("username"),
        password=ADDON.getSetting("password"),
        token_path=os.path.join(profile_dir(), ".magio_token.json"),
        language=ADDON.getSetting("language") or "SK",
        log=log,
    )


_client = None
_vod = None
_backstage = None


def client():
    global _client
    if _client is None:
        _client = MagioClient(make_config())
        _client.ensure_session()  # refresh or full login (raises MagioError)
    return _client


def vodc():
    global _vod
    if _vod is None:
        _vod = VodClient(client())
    return _vod


def backstage():
    global _backstage
    if _backstage is None:
        _backstage = Backstage(client())
    return _backstage
