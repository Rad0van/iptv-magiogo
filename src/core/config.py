"""Configuration carried through the Magio GO core.

Each front-end builds a :class:`Config` from its own source (env vars for the
server, add-on settings for Kodi) and supplies the file paths and a ``log``
callback. Defaults capture the values the original scripts hardcoded.
"""

import socket
from dataclasses import dataclass, field
from typing import Callable


def default_device_name() -> str:
    """Default label shown for this device in the Magio account.

    Uses the machine's (short) hostname so each install identifies itself;
    falls back to a constant if the hostname can't be determined.
    """
    try:
        name = socket.gethostname().split(".", 1)[0].strip()
    except Exception:
        name = ""
    return name or "magiogo"

# Browser-ish UA used for the JSON API calls.
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/114.0.0.0 Mobile Safari/537.36"
)
# UA used when fetching the actual stream URL (must look like the native app).
STREAM_USER_AGENT = (
    "ReactNativeVideo/3.13.2 (Linux;Android 10) ExoPlayerLib/2.10.3"
)
# Returned when a stream cannot be resolved (no access / device limit / error).
NO_ACCESS_URL = "http://sledovanietv.sk/download/noAccess-sk.m3u8"


@dataclass
class Config:
    """Everything the core needs to talk to Magio GO.

    ``username``/``password`` and ``token_path`` are mandatory; the rest mirror
    the constants the original ``login.py``/``magiogo.py`` used.
    """

    username: str
    password: str
    # Where the access/refresh token JSON is persisted.
    token_path: str

    device_id: str = "ab2731523db7"
    device_name: str = field(default_factory=default_device_name)
    device_type: str = "OTT_IPAD"
    profile: str = "p5"
    drm: str = "verimatrix"
    language: str = "SK"
    app_version: str = "4.0.21"
    os_version: str = "18.0"

    # 24i Backstage CMS that drives the VOD UI (menus/pages/rows).
    backstage_service_id: str = "97c10db0-b826-11e9-8a90-434c3c7200db"
    backstage_app_id: str = "cf468b80-b962-11e9-8d2d-93cf115b6f2f"

    user_agent: str = DEFAULT_USER_AGENT
    stream_user_agent: str = STREAM_USER_AGENT
    no_access_url: str = NO_ACCESS_URL

    # Front-end supplied logger. Defaults to print for ad-hoc/CLI use; the
    # server passes print, the add-on will pass an xbmc.log wrapper.
    log: Callable[[str], None] = field(default=print)
