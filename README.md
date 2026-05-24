**IPTV Magiogo** is an IPTV service that provides a list of channels and EPG data directly from the [Magio Go](https://www.magiogo.sk/) website.

### Requirements

[magiogo](https://magiogo.sk) \
[python3](https://www.python.org/) \
some IPTV player like [kodi](https://kodi.tv/)

### Installation

You can install and run the service using [docker compose](./docker-compose.yml). \
Don't forget to update environment variables!

However, if you want to run it outside docker, install packages from [requirements.txt](./requirements.txt) and run <kbd>[src/main.py](./src/main.py)</kbd> with the following environment variables:
`MAGIO_USERNAME, MAGIO_PASSWORD, HOST`. Optional device identity:
`MAGIO_DEVICE_NAME` (label in your Magio account; default = hostname),
`MAGIO_DEVICE_ID` (the `dsid`; default = a unique value generated once and
persisted to `.magio_device_id`), `MAGIO_DEVICE_TYPE` (default `OTT_IPAD`;
`OTT_TV_ANDROID` registers as a big-screen device — only if your subscription
allows it). `GET /devices` lists the devices registered to the account;
`GET /devices/delete/<id>` removes one (id from `/devices`).

```bash
$ pip install -r requirements.txt
$ MAGIO_USERNAME=hello MAGIO_PASSWORD=asd HOST=localhost:4589 python src/main.py
```

### Routes

- `/` - list of channels (viewable in browser)
- `/service/playlist` - m3u playlist
- `/service/epg` - epg data (xmltv format)

#### VOD (movies / series / documentaries)

Reverse-engineered from the Magio GO Android app and verified against a live
account. VOD lives on the same host/auth as live TV; titles resolve to **signed
HLS** streams (no DRM, same as live channels). Some titles are device-restricted
("only watchable on TVs") and won't resolve.

**Browse/play in a plain player (VLC):**

- `/vod/playlist` - flat **M3U** playable in VLC. Params: `category`, `genre`,
  `type` (`MOVIE`/`EPISODE`), `serie=<id>` (a series' episodes), `free=1` (only
  titles that play without an extra subscription), `filter` (raw RSQL),
  `sorting`, `limit`, `offset`. Entries are grouped by package; titles needing a
  subscription are prefixed 🔒.
- `/vod/watch/<id>` - 302-redirects to the resolved stream (single item).

  e.g. open `http://localhost:4589/vod/playlist?category=104&free=1` in VLC for
  free documentaries.

**JSON data API (for the planned Kodi add-on):**

- `/vod/categories`, `/vod/genres` - taxonomy. Documentaries are category `104`.
- `/vod/movies` - movie/episode list; same query params as the playlist
- `/vod/series` - series list, each with embedded `seasons`
- `/vod/series/<id>/episodes` - episodes of a series (optional `?season=<seasonId>`)
- `/vod/stream/<id>` - resolved stream descriptor (manifest URL + Kodi props)
- `/vod/play/<id>` - one-entry m3u with inline `#KODIPROP:` lines, for Kodi

> Most VOD requires a subscription package; titles outside the account's
> packages return *"Nemáte oprávnenie…"*. `pckg.free` content always plays.
> `scripts/verify_vod.py` (run with `MAGIO_USERNAME`/`MAGIO_PASSWORD`) re-checks
> the API mappings against a live account.
