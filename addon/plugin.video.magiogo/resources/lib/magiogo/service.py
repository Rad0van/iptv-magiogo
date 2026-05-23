"""Background service: keeps the Live TV playlist + EPG fresh for pvr.iptvsimple.

Only active once the user has set up Live TV (the ``enable_livetv`` setting,
flipped on by the 'Set up Live TV' action). On Kodi start it ensures the files
exist and the PVR client is pointed at them (EPG is served from cache, so this
is cheap), then refreshes the EPG periodically.
"""

import xbmc

from .context import log, setting_bool
from . import iptv

REFRESH_INTERVAL = 6 * 3600  # seconds between EPG refreshes


def main():
    monitor = xbmc.Monitor()
    log("service started")

    if setting_bool("enable_livetv"):
        try:
            iptv.setup(interactive=False)  # cheap when EPG cache is fresh
        except Exception as e:  # never let the service crash Kodi
            log(f"service initial setup error: {e}")

    while not monitor.waitForAbort(REFRESH_INTERVAL):
        if not setting_bool("enable_livetv"):
            continue
        try:
            m3u_path, epg_path = iptv.generate(epg=True, force_epg=True)
            iptv.configure_iptvsimple(m3u_path, epg_path)
            iptv.reload_iptvsimple()
            log("service refreshed playlist + epg")
        except Exception as e:
            log(f"service refresh error: {e}")

    log("service stopped")
