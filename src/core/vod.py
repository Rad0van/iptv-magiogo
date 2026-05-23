"""Magio GO VOD (movies / series / documentaries) support.

Reverse-engineered from the Magio GO Android app and **verified live** against a
real account (2026-05-23). The VOD catalog lives on the same ``skgo.magio.tv``
host and uses the same bearer auth as live TV.

Key facts confirmed live:
- VOD playback reuses ``/v2/television/stream-url`` with ``service=VOD`` and
  ``id={contentId}``. It returns a **signed HLS URL** with **no DRM** (same
  mechanism as live channels) - there is no license URL. Some titles are
  device-restricted ("only watchable on TVs") and return ``success: false``.
- List items use localized lists: ``titles``/``descriptions`` are
  ``[{locale, value}]``; ``type`` is ``{key: MOVIE|EPISODE, value}``; ``images``
  are ``[{type: POSTER|PREVIEW|..., path}]``.
- Movies and episodes both come from ``/vod/movies``; series come from
  ``/vod/series`` (with embedded ``seasons`` metadata). A series' episodes are
  fetched from ``/vod/movies?filter=serieId=={id}`` (or ``serieSeasonId``).
- Series/season ids are large numbers the backend already serializes lossily;
  they round-trip fine as Python ints, so use them verbatim.
"""

from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit

import requests

from .client import STREAM_URL  # noqa: F401  (kept for reference / external use)

BASE = "https://skgo.magio.tv"

CATEGORIES_URL = BASE + "/vod/categories"
GENRES_URL = BASE + "/vod/genres"
MOVIES_URL = BASE + "/vod/movies"
SERIES_URL = BASE + "/vod/series"
RECOMMENDED_URL = BASE + "/vod/movies/recommended"
FAVOURITES_URL = BASE + "/vod/movies/favourites"

# Kodi inputstream.adaptive license_type per DRM scheme (only used if a license
# URL ever appears - regular Magio VOD is clear HLS).
DRM_WIDEVINE = "com.widevine.alpha"
DRM_PLAYREADY = "com.microsoft.playready"


# --------------------------------------------------------------------------- #
# data model
# --------------------------------------------------------------------------- #
@dataclass
class VodItem:
    """A movie, episode or series tile. ``raw`` keeps the full upstream object."""

    id: str
    type: str = ""  # MOVIE / EPISODE / SERIES
    title: str = ""
    description: str = ""
    poster: str = ""
    fanart: str = ""
    images: list = field(default_factory=list)
    duration: int = 0
    year: int = None
    genres: list = field(default_factory=list)
    parental_rating: str = ""
    # entitlement: free==True plays for everyone; otherwise needs `package`
    free: bool = None
    package: str = ""
    # episode / series linkage
    season_no: int = None
    episode_no: int = None
    serie_id: int = None
    serie_season_id: int = None
    series_title: str = ""
    season_count: int = None
    episode_count: int = None
    seasons: list = field(default_factory=list)  # raw season objects (series only)
    raw: dict = field(default_factory=dict)


@dataclass
class PlayableStream:
    """Everything a player needs to start a VOD stream."""

    url: str  # manifest URL (signed HLS for Magio VOD)
    manifest_type: str = "hls"  # 'hls' | 'mpd'
    drm_scheme: str = None  # normally None for Magio VOD
    license_url: str = None
    headers: dict = field(default_factory=dict)
    success: bool = True
    error: str = None  # e.g. "only watchable on TVs" (device restriction)
    raw: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _first(d, *keys, default=None):
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return default


def _loc(trans, locale, key="value"):
    """Pick a localized value from a ``[{locale, <key>}]`` list, with fallbacks."""
    if not isinstance(trans, list):
        return ""
    locale = (locale or "sk").lower()
    by = {
        (t.get("locale") or "").lower(): t.get(key)
        for t in trans
        if isinstance(t, dict)
    }
    return by.get(locale) or by.get("sk") or by.get("en") or (
        next((v for v in by.values() if v), "")
    )


def pick_image(images, *types):
    """Return the ``path`` of the first image matching one of ``types`` (e.g.
    POSTER, PREVIEW), else the first image with a path."""
    if not isinstance(images, list):
        return ""
    for want in types:
        for im in images:
            if isinstance(im, dict) and im.get("type") == want and im.get("path"):
                return im["path"]
    for im in images:
        if isinstance(im, dict) and im.get("path"):
            return im["path"]
    return ""


def _genre_names(categories, locale):
    out = []
    if isinstance(categories, list):
        for cat in categories:
            for g in cat.get("genreList") or []:
                name = _loc(g.get("genreTransList"), locale, "name") or g.get("key")
                if name and name not in out:
                    out.append(name)
    return out


def _items(payload):
    """Pull the list out of a list response (``items`` is the convention)."""
    if isinstance(payload, dict):
        return payload.get("items") or []
    if isinstance(payload, list):
        return payload
    return []


# --------------------------------------------------------------------------- #
# parsing
# --------------------------------------------------------------------------- #
def parse_item(raw, locale="SK"):
    """Map a ``/vod/movies`` or ``/vod/series`` object to :class:`VodItem`."""
    t = raw.get("type")
    typ = t.get("key") if isinstance(t, dict) else (t or "")
    is_series = "seasons" in raw or "seasonCount" in raw
    if is_series and not typ:
        typ = "SERIES"

    images = raw.get("images") or []
    pckg = raw.get("pckg") or {}
    package = (
        _loc(pckg.get("packageTransDtoList"), locale, "name")
        or (pckg.get("type") or {}).get("value")
        or ""
    )
    return VodItem(
        id=str(raw.get("id", "")),
        type=typ,
        title=_loc(raw.get("titles"), locale) or raw.get("titleOriginal") or "",
        description=_loc(raw.get("descriptions"), locale),
        poster=pick_image(images, "POSTER", "COVER"),
        fanart=pick_image(images, "PREVIEW", "BACKGROUND", "POSTER"),
        images=images,
        duration=raw.get("duration") or 0,
        year=raw.get("releaseYear"),
        genres=_genre_names(raw.get("categories"), locale),
        parental_rating=raw.get("parentalRating") or "",
        free=pckg.get("free"),
        package=package,
        season_no=raw.get("seasonNumber"),
        episode_no=raw.get("episodeNumber"),
        serie_id=raw.get("serieId"),
        serie_season_id=raw.get("serieSeasonId"),
        series_title=raw.get("seriesTitleOriginal") or "",
        season_count=raw.get("seasonCount"),
        episode_count=raw.get("episodeCount"),
        seasons=raw.get("seasons") or [],
        raw=raw,
    )


def parse_category(raw, locale="SK"):
    """Taxonomy node: ``{id, name, genres: [{id, name, key}]}``."""
    return {
        "id": raw.get("id"),
        "name": _loc(raw.get("categoryTransList"), locale, "name") or raw.get("type") or "",
        "genres": [parse_genre(g, locale) for g in raw.get("genreList") or []],
        "raw": raw,
    }


def parse_genre(raw, locale="SK"):
    return {
        "id": raw.get("id"),
        "key": raw.get("key"),
        "name": _loc(raw.get("genreTransList"), locale, "name") or raw.get("key") or "",
        "raw": raw,
    }


# --------------------------------------------------------------------------- #
# filter building (RSQL / FIQL, as used by the app)
# --------------------------------------------------------------------------- #
def rsql(category=None, genre=None, type=None, ids=None, group=None,
         serie_id=None, serie_season_id=None, extra=None):
    """Build an RSQL ``filter=`` value (``requests`` URL-encodes it on the wire)."""
    parts = []
    if category is not None:
        parts.append(f"categories.id==({category})")
    if genre is not None:
        parts.append(f"categories.genres.id==({genre})")
    if type:
        parts.append(f"type=={type}")
    if serie_id is not None:
        parts.append(f"serieId=={serie_id}")
    if serie_season_id is not None:
        parts.append(f"serieSeasonId=={serie_season_id}")
    if group:
        parts.append(f"searchableGroups=like=('{group}')")
    if ids:
        parts.append("id=in=(%s)" % ",".join(str(i) for i in ids))
    if extra:
        parts.append(extra)
    return ";".join(parts)


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #
class VodClient:
    """VOD catalog + stream resolution. Composes a
    :class:`~core.client.MagioClient` for auth/token handling."""

    def __init__(self, client):
        self.c = client

    def _get(self, url, params=None):
        headers, _ok = self.c.auth_headers()
        return requests.get(url, params=params, headers=headers).json()

    @property
    def _lang(self):
        return self.c.cfg.language

    # ----- taxonomy ----------------------------------------------------- #
    def categories(self, lang=None):
        lang = lang or self._lang
        payload = self._get(CATEGORIES_URL, {"language": lang.lower()})
        return payload, [parse_category(i, lang) for i in _items(payload)]

    def genres(self, lang=None):
        lang = lang or self._lang
        payload = self._get(GENRES_URL, {"language": lang.lower()})
        return payload, [parse_genre(i, lang) for i in _items(payload)]

    # ----- listings ----------------------------------------------------- #
    def _list(self, url, filter=None, sorting="publishedFrom:DESC",
              limit=24, offset=0, lang=None):
        lang = lang or self._lang
        params = {"limit": limit, "offset": offset, "getTotalCount": "true", "lang": lang}
        if filter:
            params["filter"] = filter
        if sorting:
            params["sorting"] = sorting
        payload = self._get(url, params)
        return payload, [parse_item(i, lang) for i in _items(payload)]

    def movies(self, filter=None, sorting="publishedFrom:DESC", limit=24, offset=0, lang=None):
        return self._list(MOVIES_URL, filter, sorting, limit, offset, lang)

    def series(self, filter=None, sorting=None, limit=24, offset=0, lang=None):
        # /vod/series has no publishedFrom field; default to natural order.
        return self._list(SERIES_URL, filter, sorting, limit, offset, lang)

    def recommended(self, lang=None):
        return self._list(RECOMMENDED_URL, sorting=None, lang=lang)

    def favourites(self, lang=None):
        return self._list(FAVOURITES_URL, sorting=None, lang=lang)

    def by_ids(self, ids, lang=None):
        """Materialise a carousel from a list of movie ids."""
        return self.movies(filter=rsql(ids=ids), sorting="id:ASC", limit=len(ids), lang=lang)

    def episodes(self, serie_id=None, serie_season_id=None, limit=100, offset=0, lang=None):
        """Episodes of a series (or a single season). Sorted by episode number."""
        flt = rsql(serie_id=serie_id, serie_season_id=serie_season_id)
        return self.movies(filter=flt, sorting="episodeNumber:ASC",
                           limit=limit, offset=offset, lang=lang)

    def search(self, term, limit=100, lang=None):
        """Search movies/episodes by title.

        The backend's ``title=like`` is fuzzy and pads results with unrelated
        items, so the matches are filtered client-side to titles that actually
        contain the term (case-insensitive). Returns (payload, [VodItem])."""
        clean = term.replace("'", " ").replace("(", " ").replace(")", " ").strip()
        if not clean:
            return {}, []
        payload, items = self.movies(
            filter=f"title=like=('{clean}')", sorting=None, limit=limit, lang=lang
        )
        needle = clean.lower()
        matched = [it for it in items if needle in (it.title or "").lower()]
        return payload, matched

    # ----- playback ----------------------------------------------------- #
    def get_stream(self, content_id):
        """Resolve a VOD content id (movie or episode) to a :class:`PlayableStream`.

        Reuses ``/v2/television/stream-url`` with ``service=VOD``; the response
        carries a signed HLS ``url`` and no DRM. Device-restricted titles come
        back with ``success=False`` and an ``error`` message.
        """
        req = self.c.stream_url(content_id, service="VOD", follow_redirect=False)

        url = _first(req, "url", "streamUrl", default="")
        path = urlsplit(url).path.lower()
        if path.endswith(".mpd"):
            manifest_type = "mpd"
        else:
            manifest_type = "hls"  # Magio VOD is HLS

        # Defensive: real Magio VOD has no license URL, but keep this so VOYO /
        # future DRM content still works if a license field appears.
        license_url = _first(req, "drmLicenseUrl", "licenseUrl", "widevineDrmUrl")
        drm_scheme = DRM_WIDEVINE if license_url else None

        return PlayableStream(
            url=url,
            manifest_type=manifest_type,
            drm_scheme=drm_scheme,
            license_url=license_url,
            headers={"User-Agent": self.c.cfg.stream_user_agent},
            success=bool(req.get("success")),
            error=req.get("errorMessage"),
            raw=req,
        )


# --------------------------------------------------------------------------- #
# flat M3U rendering (so VOD can be browsed/played in plain players like VLC)
# --------------------------------------------------------------------------- #
def build_vod_m3u(items, watch_base):
    """Render a list of :class:`VodItem` as a flat M3U.

    Each entry points at ``watch_base + id`` (a route that redirects to the
    resolved stream). Episodes are labelled ``Series SxEy - Episode title``.
    """
    lines = ["#EXTM3U"]
    for it in items:
        title = it.title or str(it.id)
        if it.type == "EPISODE" and (it.season_no or it.episode_no):
            se = f"S{it.season_no or 0:02d}E{it.episode_no or 0:02d}"
            show = it.series_title or ""
            title = f"{show} {se} - {it.title}".strip() if show else f"{se} - {it.title}"
        # Mark titles that need a subscription the account may not have.
        if it.free is False:
            title = f"🔒 {title}"
        logo = it.poster or it.fanart or ""
        # Group by package so free vs subscription content is obvious in VLC.
        group = it.package or (it.genres[0] if it.genres else (it.type or "VOD"))
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{title}')
        lines.append(f"{watch_base}{it.id}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# Kodi playback property generation (player-agnostic; used by server + add-on)
# --------------------------------------------------------------------------- #
def kodi_inputstream_props(stream):
    """inputstream.adaptive properties for a :class:`PlayableStream`.

    Same key/value pairs whether emitted as ``#KODIPROP:`` lines in an M3U or
    set via ``ListItem.setProperty`` in the add-on. Magio VOD is clear HLS, so
    this is normally manifest_type=hls + stream_headers; the DRM branch is a
    fallback for any future license-bearing content.
    """
    props = {
        "inputstream": "inputstream.adaptive",
        "inputstream.adaptive.manifest_type": stream.manifest_type,
    }
    hdrs = "&".join(f"{k}={quote(v)}" for k, v in (stream.headers or {}).items())
    if stream.drm_scheme:
        props["inputstream.adaptive.license_type"] = stream.drm_scheme
        if stream.license_url:
            props["inputstream.adaptive.license_key"] = (
                f"{stream.license_url}|{hdrs}|R{{SSM}}|"
            )
    elif hdrs:
        props["inputstream.adaptive.stream_headers"] = hdrs
    return props
