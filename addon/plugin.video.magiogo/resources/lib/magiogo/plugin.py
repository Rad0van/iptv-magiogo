"""Magio GO Kodi add-on router.

A plain video add-on: it renders the catalog as ``plugin://`` folders
(Live TV + VOD: categories -> movies / series -> episodes) and resolves each
item to a playable stream via the shared :mod:`core` package. Live channels play
through inputstream.ffmpegdirect (clear HLS, like the server's M3U); VOD plays
through inputstream.adaptive. Native PVR/EPG integration (self-generated
M3U/XMLTV for pvr.iptvsimple) is a later milestone.
"""

import sys
from urllib.parse import urlencode, parse_qsl

import xbmcgui
import xbmcplugin

from core import MagioError, rsql, kodi_inputstream_props

from .context import (
    client,
    vodc,
    backstage,
    log,
    notify,
    setting_bool,
    setting_int,
    has_credentials,
    open_settings,
)

HANDLE = int(sys.argv[1])
BASE = sys.argv[0]

# inputstream props for live channels (mirrors core.playlist.INPUTSTREAM_PROPS)
LIVE_PROPS = {
    "inputstream": "inputstream.ffmpegdirect",
    "mimetype": "application/x-mpegURL",
    "inputstream.ffmpegdirect.stream_mode": "timeshift",
    "inputstream.ffmpegdirect.is_realtime_stream": "true",
}


def _free_only():
    return setting_bool("vod_free_only")


def _page_size():
    return setting_int("vod_page_size", 100)


# --------------------------------------------------------------------------- #
# url + listitem helpers
# --------------------------------------------------------------------------- #
def url(**kwargs):
    return BASE + "?" + urlencode(kwargs)


def _set_info(li, title, plot="", year=None, duration=0, mediatype=""):
    try:  # Kodi 20+ InfoTagVideo API
        tag = li.getVideoInfoTag()
        tag.setTitle(title)
        if plot:
            tag.setPlot(plot)
        if year:
            tag.setYear(int(year))
        if duration:
            tag.setDuration(int(duration))
        if mediatype:
            tag.setMediaType(mediatype)
    except Exception:  # pragma: no cover - older Kodi fallback
        info = {"title": title, "plot": plot}
        if year:
            info["year"] = int(year)
        if duration:
            info["duration"] = int(duration)
        if mediatype:
            info["mediatype"] = mediatype
        li.setInfo("video", info)


def add_folder(label, *, art=None, plot="", **params):
    li = xbmcgui.ListItem(label=label)
    if art:
        li.setArt(art)
    _set_info(li, label, plot=plot)
    xbmcplugin.addDirectoryItem(HANDLE, url(**params), li, isFolder=True)


def add_playable(label, *, action, id, art=None, plot="", year=None,
                 duration=0, mediatype="video"):
    li = xbmcgui.ListItem(label=label)
    if art:
        li.setArt(art)
    _set_info(li, label, plot=plot, year=year, duration=duration, mediatype=mediatype)
    li.setProperty("IsPlayable", "true")
    xbmcplugin.addDirectoryItem(HANDLE, url(action=action, id=id), li, isFolder=False)


def _item_art(it):
    art = {}
    if it.poster:
        art["poster"] = it.poster
        art["thumb"] = it.poster
    if it.fanart:
        art["fanart"] = it.fanart
    return art


def _item_label(it):
    label = it.title or str(it.id)
    if it.free is False:
        label = f"[COLOR orange]🔒[/COLOR] {label}"
    return label


# --------------------------------------------------------------------------- #
# directories
# --------------------------------------------------------------------------- #
def root():
    add_folder("Live TV", action="live", plot="Live channels (play directly)")
    add_folder("VOD — Movies, Series, Documentaries", action="vod",
               plot="Video on demand")
    add_folder("Set up Live TV guide (PVR)", action="setup_pvr",
               plot="Generate the channel list + EPG and configure the "
                    "PVR IPTV Simple Client so channels appear in Kodi's TV guide.")
    xbmcplugin.endOfDirectory(HANDLE)


def setup_pvr():
    from . import iptv
    ok = iptv.setup(interactive=True)
    msg = ("Live TV configured — open Kodi's TV section."
           if ok else "Setup did not complete — see notification.")
    xbmcplugin.addDirectoryItem(
        HANDLE, BASE + "?action=setup_pvr",
        xbmcgui.ListItem(label=msg), isFolder=False,
    )
    xbmcplugin.endOfDirectory(HANDLE)


def live_channels():
    try:
        channels = client().get_channels()
    except MagioError as e:
        notify(e)
        channels = {}
    for cid, ch in channels.items():
        li = xbmcgui.ListItem(label=ch["name"])
        if ch.get("logo"):
            li.setArt({"thumb": ch["logo"], "icon": ch["logo"]})
        _set_info(li, ch["name"], mediatype="video")
        li.setProperty("IsPlayable", "true")
        xbmcplugin.addDirectoryItem(
            HANDLE, url(action="play_live", id=cid), li, isFolder=False
        )
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


# Magio's "Seriály" (TV series) category; series live here, organized by genre.
SERIES_CATEGORY_ID = 101


def _add_paging(payload, shown, action, **params):
    """Append a 'Next page' folder when the listing has more items."""
    total = payload.get("totalCount") if isinstance(payload, dict) else None
    offset = int(params.get("offset", 0))
    if total and (offset + shown) < total:
        add_folder("[ Next page » ]", action=action,
                   **dict(params, offset=offset + _page_size()))


# Backstage menu slugs that are live-TV/account, not VOD — skip in the VOD menu.
CMS_SKIP_SLUGS = {
    "home", "watch-tv", "my-content", "settings", "radia",
    "watch-tv_extension_tablet", "watch-tv_extension_web",
}


def vod_menu():
    """CMS-driven VOD menu (mirrors the app's 'Magio Kino' tabs/rows)."""
    add_folder("Search…", action="vod_search", plot="Search movies & episodes")
    try:
        menu = backstage().menu("MENU_MOBILES")
    except Exception as e:
        log(f"backstage menu failed: {e}")
        menu = None
    if not menu:
        notify("Couldn't load the Magio Kino menu — using categories")
        vod_menu_fallback()
        return
    for item in menu.get("items", []):
        if item.get("slug") in CMS_SKIP_SLUGS:
            continue
        label = item.get("label") or item.get("slug") or "?"
        if item.get("items"):            # a 'tabs' node (e.g. Magio Kino) -> drill in
            add_folder(label, action="cms_menu", slug=item["slug"])
        elif item.get("reference"):      # a single page
            add_folder(label, action="cms_page", ref=item["reference"])
    xbmcplugin.endOfDirectory(HANDLE)


def cms_menu(slug):
    """List the sub-tabs/pages of a Backstage 'tabs' node."""
    item = backstage().find_item(slug)
    for sub in (item.get("items") if item else []) or []:
        label = sub.get("label") or sub.get("slug") or "?"
        if sub.get("items"):
            add_folder(label, action="cms_menu", slug=sub["slug"])
        elif sub.get("reference"):
            add_folder(label, action="cms_page", ref=sub["reference"])
    xbmcplugin.endOfDirectory(HANDLE)


def cms_page(ref):
    """List a Backstage page's rows (carousels) as folders."""
    for row in backstage().page(ref):
        if (row.get("metadata") or {}).get("show") is False:
            continue
        pid = row.get("playlistId")
        # skip placeholder/test rows the CMS sometimes leaves in
        if not pid or 'titleOriginal==' in pid or 'sdsds' in pid:
            continue
        add_folder(row.get("label") or "?", action="cms_row", pid=pid)
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


def cms_row(pid, offset=0):
    """Resolve a row's playlistId and list its items (series as folders),
    paginating through the full result set with a 'Next page' item."""
    payload, items = backstage().resolve_row(pid, offset=offset, limit=_page_size())
    has_series = False
    for it in items:
        if _free_only() and it.free is False:
            continue
        if it.type == "SERIES":
            has_series = True
            add_folder(it.title or str(it.id), action="vod_series_detail", id=it.id,
                       art=_item_art(it), plot=it.description)
        else:
            add_playable(_item_label(it), action="play_vod", id=it.id, art=_item_art(it),
                         plot=it.description, year=it.year, duration=it.duration,
                         mediatype="video")
    _add_paging(payload, len(items), "cms_row", pid=pid, offset=offset)
    xbmcplugin.setContent(HANDLE, "tvshows" if has_series else "movies")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_menu_fallback():
    """Raw-taxonomy VOD menu, used if the Backstage CMS is unavailable."""
    add_folder("Series (by genre)", action="vod_series_genres",
               plot="TV series, grouped by genre")
    _payload, cats = vodc().categories()
    for c in cats:
        if c["id"] == SERIES_CATEGORY_ID:
            continue
        add_folder(c["name"], action="vod_category", id=c["id"],
                   plot=f"{len(c['genres'])} genres")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_search():
    term = xbmcgui.Dialog().input("Search Magio GO VOD")
    if not term:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    # Note: the backend only title-searches movies/episodes, not series.
    _payload, items = vodc().search(term, limit=_page_size())
    for m in items:
        if _free_only() and m.free is False:
            continue
        add_playable(_item_label(m), action="play_vod", id=m.id, art=_item_art(m),
                     plot=m.description, year=m.year, duration=m.duration,
                     mediatype="video")
    xbmcplugin.setContent(HANDLE, "movies")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_category(cid, offset=0):
    payload, movies = vodc().movies(
        filter=rsql(category=cid, type="MOVIE"), limit=_page_size(), offset=offset
    )
    for m in movies:
        if _free_only() and m.free is False:
            continue
        add_playable(_item_label(m), action="play_vod", id=m.id, art=_item_art(m),
                     plot=m.description, year=m.year, duration=m.duration,
                     mediatype="movie")
    _add_paging(payload, len(movies), "vod_category", id=cid, offset=offset)
    xbmcplugin.setContent(HANDLE, "movies")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_series_genres():
    _payload, cats = vodc().categories()
    sercat = next((c for c in cats if c["id"] == SERIES_CATEGORY_ID), None)
    add_folder("All series", action="vod_series_genre", id=0)
    for g in (sercat["genres"] if sercat else []):
        add_folder(g["name"], action="vod_series_genre", id=g["id"])
    xbmcplugin.endOfDirectory(HANDLE)


def vod_series_genre(genre_id, offset=0):
    flt = None if str(genre_id) == "0" else rsql(genre=genre_id)
    payload, series = vodc().series(filter=flt, limit=_page_size(), offset=offset)
    for s in series:
        add_folder(s.title or str(s.id), action="vod_series_detail", id=s.id,
                   art=_item_art(s), plot=s.description)
    _add_paging(payload, len(series), "vod_series_genre", id=genre_id, offset=offset)
    xbmcplugin.setContent(HANDLE, "tvshows")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_series_detail(sid):
    _payload, eps = vodc().episodes(serie_id=sid, limit=300)
    eps.sort(key=lambda e: ((e.season_no or 0), (e.episode_no or 0)))
    for e in eps:
        if _free_only() and e.free is False:
            continue
        se = f"S{e.season_no or 0:02d}E{e.episode_no or 0:02d}"
        label = f"{se} — {e.title}" if e.title else se
        if e.free is False:
            label = f"[COLOR orange]🔒[/COLOR] {label}"
        add_playable(label, action="play_vod", id=e.id, art=_item_art(e),
                     plot=e.description, duration=e.duration, mediatype="episode")
    xbmcplugin.setContent(HANDLE, "episodes")
    xbmcplugin.endOfDirectory(HANDLE)


# --------------------------------------------------------------------------- #
# playback
# --------------------------------------------------------------------------- #
def play_live(args):
    cid = args["id"]
    utc = args.get("utc")  # set by the EPG catchup-source for archive playback
    try:
        if utc:
            utcend = args.get("utcend") or str(int(utc) + 10800)
            stream = client().get_catchup(cid, utc, utcend)
        else:
            stream = client().get_stream(cid)
    except MagioError as e:
        notify(e)
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return
    li = xbmcgui.ListItem(path=stream)
    for k, v in LIVE_PROPS.items():
        li.setProperty(k, v)
    li.setMimeType("application/x-mpegURL")
    li.setContentLookup(False)
    xbmcplugin.setResolvedUrl(HANDLE, True, li)


def play_vod(content_id):
    stream = vodc().get_stream(content_id)
    if not stream.success or not stream.url:
        notify(stream.error or "Stream unavailable")
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
        return

    props = kodi_inputstream_props(stream)

    # Only DRM streams use inputstream.adaptive; make sure it's available then.
    if props.get("inputstream") == "inputstream.adaptive":
        try:
            import inputstreamhelper  # noqa
            helper = inputstreamhelper.Helper(stream.manifest_type)
            if not helper.check_inputstream():
                notify("inputstream.adaptive is required")
                xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
                return
        except ImportError:
            pass

    li = xbmcgui.ListItem(path=stream.url)
    for k, v in props.items():
        li.setProperty(k, v)
    if "mimetype" in props:
        li.setMimeType(props["mimetype"])
    li.setContentLookup(False)
    xbmcplugin.setResolvedUrl(HANDLE, True, li)


# --------------------------------------------------------------------------- #
# dispatch
# --------------------------------------------------------------------------- #
ROUTES = {
    None: root,
    "live": live_channels,
    "vod": vod_menu,
    "vod_search": vod_search,
    "vod_series_genres": vod_series_genres,
    "setup_pvr": setup_pvr,
}


def _dispatch(action, args):
    if action in ROUTES:
        ROUTES[action]()
    elif action == "cms_menu":
        cms_menu(args["slug"])
    elif action == "cms_page":
        cms_page(args["ref"])
    elif action == "cms_row":
        cms_row(args["pid"], int(args.get("offset", 0)))
    elif action == "vod_category":
        vod_category(args["id"], int(args.get("offset", 0)))
    elif action == "vod_series_genre":
        vod_series_genre(args["id"], int(args.get("offset", 0)))
    elif action == "vod_series_detail":
        vod_series_detail(args["id"])
    elif action == "play_live":
        play_live(args)
    elif action == "play_vod":
        play_vod(args["id"])
    else:
        log(f"unknown action: {action}")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


AUTH_ACTIONS = {
    "live", "vod", "vod_search", "vod_series_genres", "vod_series_genre",
    "vod_category", "vod_series_detail", "cms_menu", "cms_page", "cms_row",
    "play_live", "play_vod", "setup_pvr",
}


def _end_failed(action):
    if str(action or "").startswith("play"):
        xbmcplugin.setResolvedUrl(HANDLE, False, xbmcgui.ListItem())
    else:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


def run():
    args = dict(parse_qsl(sys.argv[2][1:]))
    action = args.get("action")

    # No credentials yet → guide the user to settings instead of a cryptic error.
    if action in AUTH_ACTIONS and not has_credentials():
        if xbmcgui.Dialog().yesno(
            "Magio GO", "Enter your Magio GO username and password to continue.",
            yeslabel="Open settings", nolabel="Cancel",
        ):
            open_settings()
        _end_failed(action)
        return

    try:
        _dispatch(action, args)
    except MagioError as e:
        if str(e) == "login failed":
            if xbmcgui.Dialog().yesno(
                "Magio GO", "Login failed — wrong username/password?",
                yeslabel="Open settings", nolabel="Close",
            ):
                open_settings()
        else:
            notify(e)
        _end_failed(action)
