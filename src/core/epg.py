"""XMLTV EPG generation with on-disk caching (was ``main.py:magio_epg``)."""

import os
from datetime import datetime, timedelta

import xmltv

from .common import parse_season_number


def build_epg(
    client,
    cache_path,
    days_back=0,
    days_forward=7,
    max_cache_days=7,
    generator_info_name="MagioGoIPTVServer",
    generator_info_url="",
    source_info_name="Magio GO Guide",
    source_info_url="https://skgo.magio.tv/v2/television/epg",
):
    """Return XMLTV as a string, rebuilding ``cache_path`` when it is stale.

    A cached file newer than ``max_cache_days`` is returned untouched; otherwise
    the guide is fetched for ``[-days_back, +days_forward]`` days and rewritten.
    """
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 0:
        age_days = (
            datetime.now() - datetime.fromtimestamp(os.path.getmtime(cache_path))
        ).days
        if age_days < max_cache_days:
            with open(cache_path, "r") as f:
                return f.read()

    date_from = datetime.now() - timedelta(days=days_back)
    date_to = datetime.now() + timedelta(days=days_forward)

    channels = client.get_channels()
    channel_ids = list(channels.keys())
    epg = client.get_epg(channel_ids, date_from, date_to)

    writer = xmltv.Writer(
        date=datetime.now().strftime("%Y%m%d%H%M%S"),
        generator_info_name=generator_info_name,
        generator_info_url=generator_info_url,
        source_info_name=source_info_name,
        source_info_url=source_info_url,
    )

    for id, channel in channels.items():
        channel_dict = {
            "display-name": [(channel["name"], "sk")],
            "icon": [{"src": channel["logo"]}],
            "id": id,
        }
        writer.addChannel(channel_dict)

    for channel_id, programmes in epg.items():
        for programme in programmes:
            programme_dict = {
                "category": [(genre, "en") for genre in programme.genres],
                "channel": channel_id,
                "credits": {
                    "producer": [producer for producer in programme.producers],
                    "actor": [actor for actor in programme.actors],
                    "writer": [writer_ for writer_ in programme.writers],
                    "director": [director for director in programme.directors],
                },
                "date": str(programme.year),
                "desc": [(programme.description, "")],
                "icon": [{"src": programme.poster}, {"src": programme.thumbnail}],
                "length": {"units": "seconds", "length": str(programme.duration)},
                "start": programme.start_time.strftime("%Y%m%d%H%M%S"),
                "stop": programme.end_time.strftime("%Y%m%d%H%M%S"),
                "title": [(programme.title, "")],
            }

            # Define episode info only if provided
            if programme.episodeNo is not None:
                # Since seasonNo seems to be always null, try parsing the season
                # from the title (e.g. Kosti X. = 10)
                if programme.seasonNo is None:
                    (show_title_sans_season, programme.seasonNo) = parse_season_number(
                        programme.title
                    )
                    programme_dict["title"] = [(show_title_sans_season, "")]

                programme_dict["episode-num"] = [
                    (
                        f"{(programme.seasonNo or 1) - 1} . {(programme.episodeNo or 1) - 1} . 0",
                        "xmltv_ns",
                    )
                ]

            writer.addProgramme(programme_dict)

    writer.write(cache_path, True)

    with open(cache_path, "r") as f:
        return f.read()
