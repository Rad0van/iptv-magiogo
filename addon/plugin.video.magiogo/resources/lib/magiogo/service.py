"""Background service: keeps the Live TV playlist + EPG fresh for pvr.iptvsimple.

Only active once the user has run 'Set up Live TV' (the ``enable_livetv``
setting). It just (re)writes the local playlist/EPG files; pvr.iptvsimple picks
up changes on its own refresh interval. It never enables/disables the PVR client
(that crashes Kodi) and never reconfigures it.
"""

import xbmc

from .context import log, setting_bool
from . import iptv

REFRESH_INTERVAL = 6 * 3600  # seconds between EPG refreshes


def main():
    monitor = xbmc.Monitor()
    log("service started")

    # On startup only generate if enabled and the files are missing, so normal
    # startups stay cheap (EPG is otherwise refreshed on the interval below).
    if setting_bool("enable_livetv") and not iptv.files_exist():
        try:
            iptv.generate(epg=True)
        except Exception as e:  # never let the service crash Kodi
            log(f"service initial generate error: {e}")

    while not monitor.waitForAbort(REFRESH_INTERVAL):
        if not setting_bool("enable_livetv"):
            continue
        try:
            iptv.generate(epg=True, force_epg=True)
            log("service refreshed playlist + epg")
        except Exception as e:
            log(f"service refresh error: {e}")

    log("service stopped")
