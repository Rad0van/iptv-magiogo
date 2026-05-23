"""Magio GO API client.

Ports the logic that lived in ``login.py`` (auth/token storage/device
registration) and ``magiogo.py`` (channels/stream/catchup/EPG) into a single
config-driven client. No printing, no ``sys.exit``, no hardcoded paths -
failures are logged through ``config.log`` or raised as :class:`MagioError`.

Original source: https://github.com/Saros72/IPTV-Web-Server
"""

import json
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests

INIT_URL = "https://skgo.magio.tv/v2/auth/init"
LOGIN_URL = "https://skgo.magio.tv/v2/auth/login"
TOKENS_URL = "https://skgo.magio.tv/v2/auth/tokens"
CHANNELS_URL = "https://skgo.magio.tv/v2/television/channels"
CATEGORIES_URL = "https://skgo.magio.tv/home/categories"
STREAM_URL = "https://skgo.magio.tv/v2/television/stream-url"
EPG_URL = "https://skgo.magio.tv/v2/television/epg"


class MagioError(Exception):
    """Raised for unrecoverable conditions (e.g. failed login)."""


class MagioClient:
    """Talks to the Magio GO backend on behalf of a single account."""

    def __init__(self, config):
        self.cfg = config

    # ------------------------------------------------------------------ #
    # headers / token storage
    # ------------------------------------------------------------------ #
    def _base_headers(self):
        return {
            "Origin": "https://www.magiogo.sk",
            "Pragma": "no-cache",
            "Referer": "https://www.magiogo.sk/",
            "User-Agent": self.cfg.user_agent,
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "cross-site",
        }

    def _load_tokens(self):
        try:
            with open(self.cfg.token_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data["accesstoken"], data["refreshtoken"]
        except Exception:
            return "", ""

    def _save_tokens(self, access, refresh):
        with open(self.cfg.token_path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"accesstoken": access, "refreshtoken": refresh}, indent=4))

    def _refresh_tokens(self):
        """POST the refresh token; persist and return the new access token.

        Returns ``(success, access_token)``. On failure the previously stored
        access token is returned so callers can replicate the original
        per-endpoint fallback behaviour.
        """
        access, refresh = self._load_tokens()
        req = requests.post(
            TOKENS_URL, json={"refreshToken": refresh}, headers=self._base_headers()
        ).json()
        if req.get("success"):
            access = req["token"]["accessToken"]
            refresh = req["token"]["refreshToken"]
            self._save_tokens(access, refresh)
            return True, access
        return False, access

    def ensure_session(self):
        """Guarantee a usable access token for this process.

        The server establishes auth once via :meth:`register_device` at startup;
        a stateless caller (e.g. the Kodi add-on, a fresh process per action)
        instead calls this: refresh the persisted token, or do a full login if
        there is no valid refresh token yet. Raises :class:`MagioError` if login
        fails (bad credentials).
        """
        ok, access = self._refresh_tokens()
        if ok and access:
            return
        a, r = self.login()
        if not a:
            raise MagioError("login failed")
        self._save_tokens(a, r)

    def auth_headers(self):
        """Refresh the token and return base headers with a Bearer authorization.

        Public helper reused by the VOD client (:mod:`core.vod`). Returns
        ``(headers, ok)`` where ``ok`` mirrors :meth:`_refresh_tokens`.
        """
        ok, access = self._refresh_tokens()
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access
        return headers, ok

    def stream_url(self, id, service="LIVE", follow_redirect=True, extra_params=None):
        """Generic ``/v2/television/stream-url`` call.

        ``service`` is one of LIVE / ARCHIVE / DVR / VOD. Returns the raw JSON
        response dict (plus, when ``follow_redirect`` and the call succeeds, a
        synthetic ``"resolvedUrl"`` key with the redirect ``Location``). Live
        playback historically needs the redirect followed; DRM/VOD manifests are
        usually handed to the player directly, so callers can opt out.
        """
        headers, ok = self.auth_headers()
        params = {
            "service": service,
            "name": self.cfg.device_name,
            "devtype": self.cfg.device_type,
            "id": int(str(id).split(".")[0]),
            "prof": self.cfg.profile,
            "ecid": "",
            "drm": self.cfg.drm,
        }
        if extra_params:
            params.update(extra_params)
        req = requests.get(STREAM_URL, params=params, headers=headers).json()
        if follow_redirect and req.get("success") and req.get("url"):
            url = req["url"]
            stream_headers = {
                "Host": urlparse(url).netloc,
                "User-Agent": self.cfg.stream_user_agent,
                "Connection": "Keep-Alive",
            }
            r = requests.get(url, headers=stream_headers, allow_redirects=False)
            req["resolvedUrl"] = r.headers.get("location", url)
        return req

    # ------------------------------------------------------------------ #
    # auth / registration
    # ------------------------------------------------------------------ #
    def login(self):
        """Log in and return ``(access_token, refresh_token)`` (``"", ""`` on failure)."""
        params = {
            "dsid": self.cfg.device_id,
            "deviceName": self.cfg.device_name,
            "deviceType": self.cfg.device_type,
            "osVersion": self.cfg.os_version,
            "appVersion": self.cfg.app_version,
            "language": self.cfg.language,
        }
        response = requests.post(
            INIT_URL, params=params, headers=self._base_headers()
        ).json()
        access_token = response["token"]["accessToken"]

        login_params = {
            "loginOrNickname": self.cfg.username,
            "password": self.cfg.password,
        }
        login_headers = self._base_headers()
        login_headers["authorization"] = "Bearer " + access_token

        login_response = requests.post(
            LOGIN_URL, json=login_params, headers=login_headers
        ).json()

        if login_response["success"]:
            return (
                login_response["token"]["accessToken"],
                login_response["token"]["refreshToken"],
            )
        self.cfg.log(login_response["errorMessage"])
        return "", ""

    def register_device(self):
        """Register the device and persist the tokens.

        Raises :class:`MagioError` if login fails (the server adapter turns
        that into a process exit, matching the original ``sys.exit(1)``).
        """
        access_token, refresh_token = self.login()
        if not access_token:
            raise MagioError("login failed")

        params = {"list": "LIVE", "queryScope": "LIVE"}
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access_token
        response = requests.get(CHANNELS_URL, params=params, headers=headers).json()
        channel_id = response["items"][0]["channel"]["channelId"]

        stream_params = {
            "service": "LIVE",
            "name": self.cfg.device_name,
            "devtype": self.cfg.device_type,
            "id": channel_id,
            "prof": self.cfg.profile,
            "ecid": "",
            "drm": self.cfg.drm,
        }
        stream_response = requests.get(
            STREAM_URL, params=stream_params, headers=headers
        ).json()

        if stream_response["success"]:
            access_token, refresh_token = self.login()
            self._save_tokens(access_token, refresh_token)
            self.cfg.log("Login successful")
        else:
            self.cfg.log(
                stream_response["errorMessage"].replace(
                    "exceeded-max-device-count", "Exceeded maximum device count"
                )
            )

    # ------------------------------------------------------------------ #
    # data
    # ------------------------------------------------------------------ #
    def get_channels(self):
        """Return ``{channel_id: {name, logo, group}}`` for all LIVE channels."""
        _ok, access = self._refresh_tokens()
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access
        params = {"list": "LIVE", "queryScope": "LIVE"}
        ch = {}

        try:
            req = requests.get(
                CATEGORIES_URL, params={"language": "sk"}, headers=headers
            ).json()["categories"]
            categories = {
                c["channelId"]: cc["name"] for cc in req for c in cc["channels"]
            }

            req = requests.get(
                CHANNELS_URL, params=params, headers=headers
            ).json()["items"]
            for c in req:
                group = categories[c["channel"]["channelId"]]
                ch[str(c["channel"]["channelId"])] = {
                    "name": c["channel"]["name"],
                    "logo": c["channel"]["logoUrl"],
                    "group": group,
                }
        except Exception:
            pass

        return ch

    def get_stream(self, id):
        """Resolve the live HLS URL for a channel id (``no_access_url`` on failure)."""
        ok, access = self._refresh_tokens()
        if not ok:
            return self.cfg.no_access_url

        params = {
            "service": "LIVE",
            "name": self.cfg.device_name,
            "devtype": self.cfg.device_type,
            "id": int(str(id).split(".")[0]),
            "prof": self.cfg.profile,
            "ecid": "",
            "drm": self.cfg.drm,
        }
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access
        req = requests.get(STREAM_URL, params=params, headers=headers).json()

        if req["success"]:
            url = req["url"]
            stream_headers = {
                "Host": urlparse(url).netloc,
                "User-Agent": self.cfg.stream_user_agent,
                "Connection": "Keep-Alive",
            }
            req = requests.get(url, headers=stream_headers, allow_redirects=False)
            return req.headers["location"]

        self.cfg.log(str(req))
        return self.cfg.no_access_url

    def get_catchup(self, id, utc, utcend):
        """Resolve an archive/catchup stream URL for the given time window."""
        id = int(str(id).split(".")[0])

        ok, access = self._refresh_tokens()
        if not ok:
            return self.cfg.no_access_url

        params = {
            "service": "ARCHIVE",
            "name": self.cfg.device_name,
            "devtype": self.cfg.device_type,
            "id": id,
            "prof": self.cfg.profile,
            "ecid": "",
            "drm": self.cfg.drm,
        }
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access

        # Format start and end times
        date_time_start = datetime.fromtimestamp(int(utc))
        d_start = date_time_start.strftime("%Y-%m-%dT%H:%M:%S")
        date_time_end = datetime.fromtimestamp(int(utcend) + 15)
        d_end = date_time_end.strftime("%Y-%m-%dT%H:%M:%S")

        # Find the schedule covering the requested window
        epg_url = (
            f"https://skgo.magio.tv/v2/television/epg?filter=channel.id=={id}"
            f"%20and%20startTime=ge={d_start}.000Z%20and%20endTime=le={d_end}.000Z&limit=10&offset=0&lang=SK"
        )
        req = requests.get(epg_url, params=params, headers=headers).json()

        if req["success"]:
            scheduleId = str(req["items"][0]["programs"][0]["scheduleId"])
            params["id"] = int(scheduleId)

            req = requests.get(STREAM_URL, params=params, headers=headers).json()
            if req["success"]:
                return req["url"]

        return self.cfg.no_access_url

    def get_epg(self, channels, from_date, to_date):
        """Return ``{channel_id: [Programme, ...]}`` between the two dates."""
        from_date = from_date.replace(hour=0, minute=0, second=0, microsecond=0)
        to_date = to_date.replace(
            hour=0, minute=0, second=0, microsecond=0
        ) + timedelta(days=1)
        now = datetime.utcnow()

        days = int((to_date - from_date).days)

        _ok, access = self._refresh_tokens()
        headers = self._base_headers()
        headers["authorization"] = "Bearer " + access

        result = {}

        for n in range(days):
            current_day = from_date + timedelta(n)

            filter = "startTime=ge=%sT00:00:00.000Z;startTime=le=%sT00:59:59.999Z" % (
                current_day.strftime("%Y-%m-%d"),
                (current_day + timedelta(days=1)).strftime("%Y-%m-%d"),
            )

            fetch_more = True
            offset = 0
            while fetch_more:
                params = {
                    "name": self.cfg.device_name,
                    "devtype": self.cfg.device_type,
                    # The list endpoint ignores this id; kept to match the original.
                    "id": id,
                    "prof": self.cfg.profile,
                    "ecid": "",
                    "drm": self.cfg.drm,
                    "lang": "SK",
                    "offset": offset * 20,
                    "list": "LIVE",
                    "filter": filter,
                }

                req = requests.get(EPG_URL, params=params, headers=headers).json()

                fetch_more = len(req["items"]) == 20
                offset = offset + 1

                for i in req["items"]:
                    for p in i["programs"]:
                        channel = str(p["channel"]["id"])

                        if channel not in channels:
                            continue

                        if channel not in result:
                            result[channel] = []

                        programme = _programme_data(p["program"])
                        programme.start_time = datetime.utcfromtimestamp(
                            p["startTimeUTC"] / 1000
                        )
                        programme.end_time = datetime.utcfromtimestamp(
                            p["endTimeUTC"] / 1000
                        )
                        programme.duration = p["duration"]
                        programme.is_replyable = (
                            programme.start_time > (now - timedelta(days=7))
                        ) and (programme.end_time < now)

                        result[channel].append(programme)

        return result


class Base:
    def __repr__(self):
        return str(self.__dict__)


class Programme(Base):
    def __init__(self):
        self.id = ""  # type: str
        # Programme Start Time in UTC
        self.start_time = None  # type: datetime or None
        # Programme End Time in UTC
        self.end_time = None  # type: datetime or None
        self.title = ""
        self.description = ""
        self.thumbnail = ""
        self.poster = ""
        self.duration = 0
        self.genres = []  # type: List[str]
        self.actors = []  # type: List[str]
        self.directors = []  # type: List[str]
        self.writers = []  # type: List[str]
        self.producers = []  # type: List[str]
        self.seasonNo = None
        self.episodeNo = None
        self.year = None  # type: int or None
        self.is_replyable = False
        # programme metadata
        self.metadata = {}  # type: Dict[str, int]


def _programme_data(pi):
    def safe_int(value, default=None):
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    programme = Programme()
    programme.id = pi["programId"]
    programme.title = pi["title"]
    programme.description = "%s\n%s" % (
        pi["episodeTitle"] or "",
        pi["description"] or "",
    )

    pv = pi["programValue"]
    if pv["episodeId"] is not None:
        programme.episodeNo = safe_int(pv["episodeId"])
    if pv["seasonNumber"] is not None:
        programme.seasonNo = safe_int(pv["seasonNumber"])
    if pv["creationYear"] is not None:
        programme.year = safe_int(pv["creationYear"])
    for i in pi["images"]:
        programme.thumbnail = i
        break
    for i in pi["images"]:
        if "_VERT" in i:
            programme.poster = i
            break
    for d in pi["programRole"]["directors"]:
        programme.directors.append(d["fullName"])
    for a in pi["programRole"]["actors"]:
        programme.actors.append(a["fullName"])
    if pi["programCategory"] is not None:
        for c in pi["programCategory"]["subCategories"]:
            programme.genres.append(c["desc"])

    return programme
