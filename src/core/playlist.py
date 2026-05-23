"""M3U playlist generation (was ``main.py:magio_playlist``)."""

# Inputstream properties emitted per channel so Kodi plays the HLS stream with
# inputstream.ffmpegdirect in timeshift mode.
INPUTSTREAM_PROPS = (
    "#KODIPROP:inputstream=inputstream.ffmpegdirect\n"
    "#KODIPROP:mimetype=application/x-mpegURL\n"
    "#KODIPROP:inputstream.ffmpegdirect.stream_mode=timeshift\n"
    "#KODIPROP:inputstream.ffmpegdirect.is_realtime_stream=true\n"
)

# Appended to each #EXTINF; IPTV Simple substitutes {utc}/{utcend} for catchup.
CATCHUP = ' catchup="append" catchup-source="?utc={utc}&utcend={utcend}",'


def build_kodi_playlist(client, plugin_url):
    """M3U for pvr.iptvsimple where every channel plays via the add-on.

    Each channel URL is a ``plugin://`` callback (``?action=play_live&id=<id>``)
    so the add-on resolves a fresh, token-authorized stream per play and sets the
    inputstream properties itself (no ``#KODIPROP`` needed here). ``tvg-id``
    matches the XMLTV channel id for EPG linkage. Catchup is wired via an
    absolute ``catchup-source`` whose ``{utc}``/``{utcend}`` placeholders
    pvr.iptvsimple substitutes.

    ``plugin_url`` is e.g. ``plugin://plugin.video.magiogo/``.
    """
    ch = client.get_channels()
    if not ch:
        return ""
    lines = ["#EXTM3U"]
    for cid, y in ch.items():
        play = f"{plugin_url}?action=play_live&id={cid}"
        catchup = (
            f"{plugin_url}?action=play_live&id={cid}&utc={{utc}}&utcend={{utcend}}"
        )
        lines.append(
            f'#EXTINF:-1 provider="Magio GO" group-title="{y["group"]}" '
            f'tvg-id="{cid}" tvg-logo="{y["logo"]}" '
            f'catchup="append" catchup-source="{catchup}",{y["name"]}'
        )
        lines.append(play)
    return "\n".join(lines) + "\n"


def build_playlist(client, stream_base):
    """Build an M3U string. ``stream_base`` is prepended to ``<id>.m3u8``.

    The server passes e.g. ``http://host:port/service/`` so each channel points
    back at its resolving route.
    """
    ch = client.get_channels()
    t = ""
    for x, y in ch.items():
        t = (
            t
            + '#EXTINF:-1 provider="Magio GO" group-title="'
            + y["group"]
            + '" tvg-id="'
            + str(x)
            + '" tvg-logo="'
            + y["logo"]
            + '"'
            + CATCHUP
            + y["name"]
            + "\n"
            + INPUTSTREAM_PROPS
            + stream_base
            + str(x)
            + ".m3u8\n"
        )
    if t != "":
        t = "#EXTM3U\n" + t
    return t
