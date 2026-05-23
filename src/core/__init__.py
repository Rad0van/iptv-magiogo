"""I/O-agnostic Magio GO core.

Shared by the standalone server (``src/main.py``) and the Kodi add-on. No
Bottle, no ``os.environ``, no hardcoded paths and no ``print`` live here -
everything is driven through a :class:`~core.config.Config` whose ``log``
callback and file paths are supplied by each front-end.
"""

from .config import Config
from .client import MagioClient, MagioError
from .playlist import build_playlist, build_kodi_playlist
from .epg import build_epg
from .vod import (
    VodClient,
    VodItem,
    PlayableStream,
    rsql,
    kodi_inputstream_props,
    build_vod_m3u,
)
from .backstage import Backstage

__all__ = [
    "Config",
    "MagioClient",
    "MagioError",
    "build_playlist",
    "build_kodi_playlist",
    "build_epg",
    "VodClient",
    "VodItem",
    "PlayableStream",
    "rsql",
    "kodi_inputstream_props",
    "build_vod_m3u",
    "Backstage",
]
