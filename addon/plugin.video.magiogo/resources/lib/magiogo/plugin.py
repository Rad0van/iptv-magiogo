"""Magio GO Kodi add-on router.

A plain video add-on: it renders the catalog as ``plugin://`` folders
(Live TV + VOD: categories -> movies / series -> episodes) and resolves each
item to a playable stream via the shared :mod:`core` package. Live channels play
through inputstream.ffmpegdirect (clear HLS, like the server's M3U); VOD plays
through inputstream.adaptive. Native PVR/EPG integration (self-generated
M3U/XMLTV for pvr.iptvsimple) is a later milestone.
"""

import sys
from urllib.parse import urlencode, parse_qsl, quote

import xbmc
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


# Locked items are shown in red: a red icon + red label, plus the ParentalLocked
# property (the one thing the skin can read that survives the thumb-loader). A
# red folder marks a fully-locked folder, a red padlock a locked playable item.
# Only the icon art is overridden so poster/wall views keep the real artwork; in
# Estuary's list view the icon comes from the skin (see scripts/patch_estuary_lock.sh).
RES = "special://home/addons/plugin.video.magiogo/resources"
FOLDER_RED = RES + "/folder_red.png"
LOCK_RED = RES + "/lock_red.png"


def _red(label):
    return f"[COLOR red]{label}[/COLOR]"


def _locked_art(art, icon):
    a = dict(art or {})
    a["icon"] = icon
    return a


def add_folder(label, *, art=None, plot="", locked=False, **params):
    li = xbmcgui.ListItem(label=_red(label) if locked else label)
    li.setArt(_locked_art(art, FOLDER_RED) if locked else (art or {}))
    if locked:
        # A skin can show a lock badge for this (survives the thumb-loader,
        # unlike the overlay). Estuary uses ParentalLocked for the PVR lock.
        li.setProperty("ParentalLocked", "true")
    _set_info(li, label, plot=plot)  # clean title (no colour markup) for metadata
    xbmcplugin.addDirectoryItem(HANDLE, url(**params), li, isFolder=True)


def add_playable(label, *, action, id, art=None, plot="", year=None,
                 duration=0, mediatype="video", locked=False):
    li = xbmcgui.ListItem(label=_red(label) if locked else label)
    li.setArt(_locked_art(art, LOCK_RED) if locked else (art or {}))
    if locked:
        li.setProperty("ParentalLocked", "true")
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
    return it.title or str(it.id)


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
    add_folder("My devices", action="devices",
               plot="Devices registered to your Magio GO account.")
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


def _is_vod_row(pid):
    """Rows we can actually browse/play: VOD movie or series queries. Other rows
    (continue-watching, live, schedules…) carry non-VOD ids and would only
    produce confusing playback errors, so they're skipped."""
    return "vod/movies" in pid or "vod/series" in pid


def _row_all_locked(bs, pid, headers):
    """True if every item in a (movie) row needs another subscription. Series
    rows can't be judged (series expose no entitlement flag) so return False."""
    if "vod/movies" not in pid:
        return False
    try:
        _p, items = bs.resolve_row(pid, offset=0, limit=50, headers=headers)
    except Exception:
        return False
    return bool(items) and all(it.free is False for it in items)


def cms_page(ref):
    """List a Backstage page's rows (carousels) as folders, flagging a row "(locked)"
    when all of its items need another subscription. Lock checks reuse one auth
    token and run in parallel to keep the page snappy."""
    import concurrent.futures

    bs = backstage()
    rows = []
    for row in bs.page(ref):
        if (row.get("metadata") or {}).get("show") is False:
            continue
        pid = row.get("playlistId") or ""
        if 'titleOriginal==' in pid or 'sdsds' in pid or not _is_vod_row(pid):
            continue  # placeholder/test rows and rows we can't play
        rows.append((row.get("label") or "?", pid))

    headers, _ok = client().auth_headers()  # one refresh, reused below
    movie_pids = [pid for _l, pid in rows if "vod/movies" in pid]
    locked = {}
    if movie_pids:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(_row_all_locked, bs, pid, headers): pid for pid in movie_pids}
            for f in concurrent.futures.as_completed(futs):
                locked[futs[f]] = f.result()

    for label, pid in rows:
        add_folder(label, action="cms_row", pid=pid, locked=locked.get(pid, False))
    xbmcplugin.setContent(HANDLE, "videos")
    xbmcplugin.endOfDirectory(HANDLE)


_VOD_PAGE = 500  # the /vod/movies endpoint hard-caps every response at 500 rows


def _series_locked_map(bs, series_ids, headers):
    """{series_id: all_episodes_locked} from the series' episodes.

    Series carry no entitlement flag, so lock status is derived from their
    episodes (which do), via a batched ``serieId=in=(…)`` query. The endpoint
    caps responses at 500 rows regardless of the requested limit, so we PAGINATE
    until every episode is fetched — otherwise series whose episodes fall beyond
    the first 500 would look (wrongly) unlocked."""
    if not series_ids:
        return {}
    flt = "serieId=in=(%s)" % ",".join(str(s) for s in series_ids)

    def fetch(offset):
        pid = (f"vod/movies?limit={_VOD_PAGE}&offset={offset}"
               "&getTotalCount=true&filter=" + quote(flt))
        return bs.resolve_row(pid, headers=headers)

    try:
        payload, eps = fetch(0)
    except Exception:
        return {}
    total = (payload or {}).get("totalCount") if isinstance(payload, dict) else None
    if total and total > len(eps):
        # fetch the remaining pages in parallel (cap at ~12 pages for safety)
        import concurrent.futures
        offsets = list(range(_VOD_PAGE, min(total, _VOD_PAGE * 12), _VOD_PAGE))
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
            for _p, more in ex.map(fetch, offsets):
                eps.extend(more)

    by_series = {}
    for ep in eps:
        if ep.serie_id is not None:
            by_series.setdefault(str(ep.serie_id), []).append(ep)
    return {
        str(sid): bool(by_series.get(str(sid)))
        and all(ep.free is False for ep in by_series[str(sid)])
        for sid in series_ids
    }


def cms_row(pid, offset=0):
    """Resolve a row's playlistId and list its items (series as folders),
    paginating through the full result set with a 'Next page' item. Series whose
    every episode needs another subscription are flagged "(locked)"."""
    bs = backstage()
    headers, _ok = client().auth_headers()
    payload, items = bs.resolve_row(pid, offset=offset, limit=_page_size(), headers=headers)
    locked = _series_locked_map(bs, [it.id for it in items if it.type == "SERIES"], headers)
    has_series = False
    for it in items:
        if it.type == "SERIES":
            lk = locked.get(it.id, False)
            if _free_only() and lk:
                continue
            has_series = True
            add_folder(it.title or str(it.id), action="vod_series_detail", id=it.id,
                       art=_item_art(it), plot=it.description, locked=lk)
        else:
            if _free_only() and it.free is False:
                continue
            add_playable(_item_label(it), action="play_vod", id=it.id, art=_item_art(it),
                         plot=it.description, year=it.year, duration=it.duration,
                         mediatype="video", locked=(it.free is False))
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
                     mediatype="video", locked=(m.free is False))
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
                     mediatype="movie", locked=(m.free is False))
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
    headers, _ok = client().auth_headers()
    locked = _series_locked_map(backstage(), [s.id for s in series], headers)
    for s in series:
        lk = locked.get(s.id, False)
        if _free_only() and lk:
            continue
        add_folder(s.title or str(s.id), action="vod_series_detail", id=s.id,
                   art=_item_art(s), plot=s.description, locked=lk)
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
        add_playable(label, action="play_vod", id=e.id, art=_item_art(e),
                     plot=e.description, duration=e.duration, mediatype="episode",
                     locked=(e.free is False))
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


def _friendly_vod_error(err):
    """Map Magio's (Slovak) backend errors to a clear short message."""
    e = (err or "").lower()
    if "oprávneni" in e or "permission" in e:
        return "Not included in your subscription"
    if "televíz" in e or "only" in e and "tv" in e:
        return "This title plays only on a TV"
    if not err or "nastala chyba" in e:
        return "This title isn't available"
    return err


def play_vod(content_id):
    stream = vodc().get_stream(content_id)
    if not stream.success or not stream.url:
        notify(_friendly_vod_error(stream.error))
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
# devices (read-only)
# --------------------------------------------------------------------------- #
def devices():
    """Show the devices registered to the account (/v2/home/my-devices)."""
    try:
        data = client().get_devices()
    except MagioError as e:
        notify(e)
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)
        return

    seen = set()

    def add_device(d, marker=""):
        if d.get("id") in seen:
            return
        seen.add(d.get("id"))
        name = d.get("name") or d.get("deviceNickname") or "(unnamed)"
        cat = d.get("category", "")
        last = (d.get("lastLoggedOn") or "")[:10]
        li = xbmcgui.ListItem(label=name + marker)
        li.setLabel2(" · ".join(x for x in (cat, last) if x))
        _set_info(li, name, plot=(f"Category: {cat}\n"
                                  f"Last logged on: {last}\n"
                                  f"Magio device id: {d.get('id')}"))
        li.addContextMenuItems(
            [("Remove device",
              "RunPlugin(%s)" % url(action="device_remove", id=d.get("id")))])
        xbmcplugin.addDirectoryItem(HANDLE, url(action="devices"), li, isFolder=False)

    if data.get("thisDevice"):
        add_device(data["thisDevice"], "  [This device]")
    for d in data.get("smallScreenDevices") or []:
        add_device(d)
    for d in data.get("stbAndBigScreenDevices") or []:
        add_device(d)

    rem = ("Free slots — mobile/tablet: "
           f"{data.get('remainingSmallScreenDevicesCount', '?')}, "
           f"STB: {data.get('remainingSTBDevicesCount', '?')}, "
           f"big screen: {data.get('remainingBigScreenDevicesCount', '?')}")
    info = xbmcgui.ListItem(label=f"[COLOR gray]{rem}[/COLOR]")
    xbmcplugin.addDirectoryItem(HANDLE, url(action="devices"), info, isFolder=False)

    xbmcplugin.setContent(HANDLE, "files")
    xbmcplugin.endOfDirectory(HANDLE)


def device_remove(device_id):
    """Context-menu action: remove a device, then refresh the list."""
    if not xbmcgui.Dialog().yesno("Magio GO", "Remove this device from your account?"):
        return
    try:
        client().remove_device(device_id)
        notify("Device removed")
    except MagioError as e:
        notify(e)
    xbmc.executebuiltin("Container.Refresh")


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
    "devices": devices,
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
    elif action == "device_remove":
        device_remove(args["id"])
    else:
        log(f"unknown action: {action}")
        xbmcplugin.endOfDirectory(HANDLE, succeeded=False)


AUTH_ACTIONS = {
    "live", "vod", "vod_search", "vod_series_genres", "vod_series_genre",
    "vod_category", "vod_series_detail", "cms_menu", "cms_page", "cms_row",
    "play_live", "play_vod", "setup_pvr", "devices", "device_remove",
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
