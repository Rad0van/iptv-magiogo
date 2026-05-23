import os
import sys
from datetime import datetime

from bottle import route, redirect, response, request, template, run

from core import (
    Config,
    MagioClient,
    MagioError,
    build_playlist,
    build_epg,
    VodClient,
    rsql,
    kodi_inputstream_props,
    build_vod_m3u,
)

host, port = os.environ.get("HOST", "0.0.0.0:4589").split(":")
port = int(port)

EPG_CACHE = ".epg.xmltv"

cfg = Config(
    username=os.environ["MAGIO_USERNAME"],
    password=os.environ["MAGIO_PASSWORD"],
    token_path=".magio_token.json",
)
client = MagioClient(cfg)
vod = VodClient(client)


@route("/service/playlist")
def magio_playlist():
    t = build_playlist(client, f"http://{host}:{port}/service/")
    response.content_type = "text/plain; charset=UTF-8"
    return t


@route("/service/epg")
def magio_epg():
    t = build_epg(client, EPG_CACHE)
    response.content_type = "application/octet-stream"
    response.headers["Content-Disposition"] = "inline; filename=epg.xmltv"
    return t


@route("/")
def magio_list():
    names = [("/vod/browse", "▶ VOD — movies, series, documentaries")]
    info: dict = {"title": "Magio GO"}
    ch = client.get_channels()
    for x, y in ch.items():
        names.append(("/service/" + str(x) + ".m3u8", y["name"].replace(" HD", "")))
    info["names"] = names
    return template("./templates/links.tpl", info)


@route("/service/<id>")
def magio_play(id):
    print(f"Playing {id}")
    if "utc" in request.query_string:
        if "utcend" in request.query_string:
            end = request.query["utcend"]
        else:
            now = int(datetime.now().timestamp())
            end = int(request.query["utc"]) + 10800
            if end > now:
                end = now - 60
        try:
            stream = client.get_catchup(id, request.query["utc"], str(end))
        except:
            stream = client.get_stream(id)
    else:
        stream = client.get_stream(id)
    response.content_type = "application/dash+xml"
    return redirect(stream)


# --------------------------------------------------------------------------- #
# VOD (movies / series / documentaries) — reverse-engineered from the app.
# JSON browse routes + a directly-playable DRM M3U. See core/vod.py for the
# UNVERIFIED assumptions and scripts/verify_vod.py to confirm them live.
# --------------------------------------------------------------------------- #
@route("/vod/categories")
def vod_categories():
    payload, _parsed = vod.categories()
    response.content_type = "application/json; charset=UTF-8"
    return payload


@route("/vod/genres")
def vod_genres():
    payload, _parsed = vod.genres()
    response.content_type = "application/json; charset=UTF-8"
    return payload


@route("/vod/movies")
def vod_movies():
    q = request.query
    flt = q.get("filter") or rsql(
        category=q.get("category") or None,
        genre=q.get("genre") or None,
        type=q.get("type") or None,
    ) or None
    payload, _items = vod.movies(
        filter=flt,
        sorting=q.get("sorting", "publishedFrom:DESC"),
        limit=int(q.get("limit", 24)),
        offset=int(q.get("offset", 0)),
    )
    response.content_type = "application/json; charset=UTF-8"
    return payload


@route("/vod/series")
def vod_series():
    q = request.query
    flt = q.get("filter") or rsql(
        category=q.get("category") or None,
        genre=q.get("genre") or None,
    ) or None
    payload, _items = vod.series(
        filter=flt,
        sorting=q.get("sorting") or None,
        limit=int(q.get("limit", 24)),
        offset=int(q.get("offset", 0)),
    )
    response.content_type = "application/json; charset=UTF-8"
    return payload


@route("/vod/playlist")
def vod_playlist():
    """Flat M3U of a VOD listing, browsable/playable in VLC etc.

    Query params: `category`, `genre`, `type` (MOVIE/EPISODE), `serie` (series
    id -> its episodes), `filter` (raw RSQL), `sorting`, `limit`, `offset`.
    """
    q = request.query
    serie = q.get("serie")
    if serie:
        _payload, items = vod.episodes(serie_id=serie, limit=int(q.get("limit", 200)))
    else:
        flt = q.get("filter") or rsql(
            category=q.get("category") or None,
            genre=q.get("genre") or None,
            type=q.get("type") or None,
        ) or None
        _payload, items = vod.movies(
            filter=flt,
            sorting=q.get("sorting", "publishedFrom:DESC"),
            limit=int(q.get("limit", 100)),
            offset=int(q.get("offset", 0)),
        )
    if q.get("free"):  # only titles that play without an extra subscription
        items = [i for i in items if i.free]
    response.content_type = "text/plain; charset=UTF-8"
    return build_vod_m3u(items, f"http://{host}:{port}/vod/watch/")


@route("/vod/watch/<id>")
def vod_watch(id):
    """Resolve a VOD item and 302-redirect to its stream (plays directly in VLC)."""
    s = vod.get_stream(id)
    if not s.success or not s.url:
        response.status = 404
        return s.error or "stream unavailable"
    return redirect(s.url)


@route("/vod/series/<id>/episodes")
def vod_episodes(id):
    q = request.query
    payload, _items = vod.episodes(
        serie_id=id,
        serie_season_id=q.get("season") or None,
        limit=int(q.get("limit", 100)),
        offset=int(q.get("offset", 0)),
    )
    response.content_type = "application/json; charset=UTF-8"
    return payload


@route("/vod/stream/<id>")
def vod_stream(id):
    """Return the resolved VOD stream as JSON (manifest, DRM, Kodi props)."""
    s = vod.get_stream(id)
    response.content_type = "application/json; charset=UTF-8"
    return {
        "url": s.url,
        "manifest_type": s.manifest_type,
        "drm_scheme": s.drm_scheme,
        "license_url": s.license_url,
        "kodi_props": kodi_inputstream_props(s),
        "raw": s.raw,
    }


@route("/vod/play/<id>")
def vod_play(id):
    """A one-entry M3U with inline KODIPROPs so a VOD item plays (incl. DRM) in
    Kodi when opened directly."""
    s = vod.get_stream(id)
    lines = ["#EXTM3U"]
    for k, v in kodi_inputstream_props(s).items():
        lines.append(f"#KODIPROP:{k}={v}")
    lines.append(f"#EXTINF:-1,VOD {id}")
    lines.append(s.url)
    response.content_type = "text/plain; charset=UTF-8"
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# VOD HTML browser (click through the catalog in a web browser)
# --------------------------------------------------------------------------- #
def _item_card(it, episode=False):
    title = it.title or str(it.id)
    if episode and (it.season_no or it.episode_no):
        title = f"S{it.season_no or 0:02d}E{it.episode_no or 0:02d} — {it.title}"
    sub = []
    if it.year:
        sub.append(str(it.year))
    if it.duration:
        sub.append(f"{it.duration // 60} min")
    locked = it.free is False
    return {
        "href": f"/vod/watch/{it.id}",
        "img": it.poster or it.fanart or "",
        "title": title,
        "subtitle": " · ".join(sub),
        "badge": (("🔒 " if locked else "") + (it.package or "")).strip(),
        "locked": locked,
    }


def _vod_page(title, back, actions, items):
    return template("./templates/vod.tpl", title=title, back=back,
                    actions=actions, items=items)


@route("/vod/browse")
def vod_browse():
    _p, cats = vod.categories()
    items = [{"href": "/vod/browse/series", "title": "Series", "kind": "node",
              "icon": "📺", "subtitle": "TV series"}]
    for c in cats:
        items.append({"href": f"/vod/browse/category/{c['id']}", "title": c["name"],
                      "kind": "node", "icon": "🎬",
                      "subtitle": f"{len(c['genres'])} genres"})
    return _vod_page("Magio GO VOD", "/", [], items)


@route("/vod/browse/category/<id>")
def vod_browse_category(id):
    _p, cats = vod.categories()
    name = next((c["name"] for c in cats if str(c["id"]) == str(id)), f"Category {id}")
    _p2, movies = vod.movies(filter=rsql(category=id, type="MOVIE"), limit=120)
    cards = [_item_card(m) for m in movies]
    if request.query.get("free"):
        cards = [c for c in cards if not c["locked"]]
    actions = [("▶ Open all in VLC", f"/vod/playlist?category={id}"),
               ("Free only", f"/vod/browse/category/{id}?free=1")]
    return _vod_page(name, "/vod/browse", actions, cards)


@route("/vod/browse/genre/<id>")
def vod_browse_genre(id):
    _p, movies = vod.movies(filter=rsql(genre=id), limit=120)
    cards = [_item_card(m) for m in movies]
    return _vod_page(f"Genre {id}", "/vod/browse",
                     [("▶ Open all in VLC", f"/vod/playlist?genre={id}")], cards)


@route("/vod/browse/search")
def vod_browse_search():
    q = (request.query.getunicode("q") or "").strip()  # UTF-8 (Bottle defaults to latin1)
    cards = []
    if q:
        _p, items = vod.search(q, limit=120)
        cards = [_item_card(m) for m in items]
    title = f"Search: {q}" if q else "Search"
    return template("./templates/vod.tpl", title=title, back="/vod/browse",
                    actions=[], items=cards, query=q)


@route("/vod/search")
def vod_search_json():
    q = (request.query.getunicode("q") or "").strip()  # UTF-8 (Bottle defaults to latin1)
    items = []
    if q:
        _p, items = vod.search(q, limit=int(request.query.get("limit", 100)))
    response.content_type = "application/json; charset=UTF-8"
    return {
        "query": q,
        "count": len(items),
        "items": [
            {"id": i.id, "title": i.title, "type": i.type, "year": i.year,
             "free": i.free, "package": i.package, "poster": i.poster,
             "play": f"/vod/watch/{i.id}"}
            for i in items
        ],
    }


@route("/vod/browse/series")
def vod_browse_series():
    _p, series = vod.series(limit=120)
    cards = []
    for it in series:
        sub = []
        if it.season_count:
            sub.append(f"{it.season_count} seasons")
        if it.episode_count:
            sub.append(f"{it.episode_count} eps")
        cards.append({"href": f"/vod/browse/series/{it.id}",
                      "img": it.poster or it.fanart or "",
                      "title": it.title or str(it.id), "subtitle": " · ".join(sub)})
    return _vod_page("Series", "/vod/browse", [], cards)


@route("/vod/browse/series/<id>")
def vod_browse_series_detail(id):
    _p, eps = vod.episodes(serie_id=id, limit=300)
    eps.sort(key=lambda e: ((e.season_no or 0), (e.episode_no or 0)))
    name = next((e.series_title for e in eps if e.series_title), "Series")
    cards = [_item_card(e, episode=True) for e in eps]
    return _vod_page(name, "/vod/browse/series",
                     [("▶ Open all in VLC", f"/vod/playlist?serie={id}")], cards)


print("Registering device")
try:
    client.register_device()
except MagioError:
    sys.exit(1)

print("Starting server on 0.0.0.0:4589")
run(host="0.0.0.0", port=4589, reloader=False)
