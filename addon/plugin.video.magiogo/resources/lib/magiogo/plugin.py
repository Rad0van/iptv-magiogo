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


def vod_menu():
    add_folder("Search…", action="vod_search", plot="Search movies & episodes")
    add_folder("Series", action="vod_series", plot="TV series")
    _payload, cats = vodc().categories()
    for c in cats:
        add_folder(c["name"], action="vod_category", id=c["id"],
                   plot=f"{len(c['genres'])} genres")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_search():
    term = xbmcgui.Dialog().input("Search Magio GO VOD")
    if not term:
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return
    _payload, items = vodc().search(term, limit=_page_size())
    for m in items:
        if _free_only() and m.free is False:
            continue
        add_playable(_item_label(m), action="play_vod", id=m.id, art=_item_art(m),
                     plot=m.description, year=m.year, duration=m.duration,
                     mediatype="video")
    xbmcplugin.setContent(HANDLE, "movies")
    xbmcplugin.endOfDirectory(HANDLE)


def vod_category(cid):
    _payload, movies = vodc().movies(
        filter=rsql(category=cid, type="MOVIE"), limit=_page_size()
    )
    for m in movies:
        if _free_only() and m.free is False:
            continue
        add_playable(_item_label(m), action="play_vod", id=m.id, art=_item_art(m),
                     plot=m.description, year=m.year, duration=m.duration,
                     mediatype="movie")
    xbmcplugin.setContent(HANDLE, "movies")
    xbmcplugin.addSortMethod(HANDLE, xbmcplugin.SORT_METHOD_TITLE)
    xbmcplugin.endOfDirectory(HANDLE)


def vod_series_list():
    _payload, series = vodc().series(limit=_page_size())
    for s in series:
        sub = []
        if s.season_count:
            sub.append(f"{s.season_count} seasons")
        if s.episode_count:
            sub.append(f"{s.episode_count} episodes")
        add_folder(s.title or str(s.id), action="vod_series_detail", id=s.id,
                   art=_item_art(s), plot=s.description)
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

    # Make sure inputstream.adaptive (+ deps) is available.
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
    for k, v in kodi_inputstream_props(stream).items():
        li.setProperty(k, v)
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
    "vod_series": vod_series_list,
    "setup_pvr": setup_pvr,
}


def _dispatch(action, args):
    if action in ROUTES:
        ROUTES[action]()
    elif action == "vod_category":
        vod_category(args["id"])
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
    "live", "vod", "vod_search", "vod_series", "vod_category",
    "vod_series_detail", "play_live", "play_vod", "setup_pvr",
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
