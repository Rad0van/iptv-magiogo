"""24i Backstage CMS client — the headless CMS that drives the Magio GO VOD UI.

Reverse-engineered from the app: the whole VOD experience ("Magio Kino" and its
tabs Dokumenty / Šport / Lifestyle / …, and every carousel inside them) is
defined in 24i Backstage, not hardcoded. The flow is:

  GET /menus                 -> navigation tree (MENU_MOBILES/MENU_STV/MENU_WEB),
                                each a tree of "tabs"/"page" items with a slug,
                                a label and (for pages) a `reference` id.
  GET /pages/{reference}     -> an ordered list of rows (carousels). Each row has
                                a `label`, a `type`/`display` and a `playlistId`
                                which is a skgo.magio.tv /vod query (movies or
                                series, filtered by category/genre).

The playlistId is fetched with the user's bearer token to get the actual items.
Requests are authenticated to Backstage with the service + application id headers
(stable production ids embedded in the app).
"""

import requests

from .vod import parse_item, _items

BASE = "https://backstage-fapi.24i.com"
STREAM_HOST = "https://skgo.magio.tv"

# Production Magio GO Backstage service + mobile application id (stable since 2019).
DEFAULT_SERVICE_ID = "97c10db0-b826-11e9-8a90-434c3c7200db"
DEFAULT_APP_ID = "cf468b80-b962-11e9-8d2d-93cf115b6f2f"


class Backstage:
    """Reads the VOD navigation/pages from Backstage and resolves row playlists."""

    def __init__(self, client, service_id=None, app_id=None):
        self.client = client
        cfg = client.cfg
        self.service_id = (
            service_id or getattr(cfg, "backstage_service_id", None) or DEFAULT_SERVICE_ID
        )
        self.app_id = app_id or getattr(cfg, "backstage_app_id", None) or DEFAULT_APP_ID
        self.lang = cfg.language

    def _headers(self):
        return {
            "X-Service-ID": self.service_id,
            "X-Application-ID": self.app_id,
            "X-Accept-Language": self.lang.lower(),
            "User-Agent": self.client.cfg.user_agent,
        }

    def menus(self):
        data = requests.get(BASE + "/menus", headers=self._headers(), timeout=20).json()
        return data if isinstance(data, list) else []

    def menu(self, label="MENU_MOBILES"):
        return next((m for m in self.menus() if m.get("label") == label), None)

    def find_item(self, slug, menu_label="MENU_MOBILES"):
        """Find a menu item (page or tabs node) by slug, searching recursively."""
        def walk(items):
            for it in items or []:
                if it.get("slug") == slug:
                    return it
                found = walk(it.get("items"))
                if found:
                    return found
            return None

        menu = self.menu(menu_label)
        return walk(menu.get("items")) if menu else None

    def page(self, reference):
        """Return a page's rows (list of row descriptors)."""
        data = requests.get(
            BASE + f"/pages/{reference}", headers=self._headers(), timeout=20
        ).json()
        return data if isinstance(data, list) else []

    def resolve_row(self, playlist_id):
        """Fetch a row's items from its ``playlistId``.

        The playlistId is a (usually relative, already URL-encoded) skgo.magio.tv
        ``/vod/...`` query. Pass it through unchanged, prepend the host if needed,
        and add the bearer token. Returns ``(payload, [VodItem])``.
        """
        if not playlist_id:
            return {}, []
        url = (
            playlist_id
            if playlist_id.startswith("http")
            else f"{STREAM_HOST}/{playlist_id.lstrip('/')}"
        )
        headers, _ok = self.client.auth_headers()
        try:
            payload = requests.get(url, headers=headers, timeout=25).json()
        except Exception:
            return {}, []
        return payload, [parse_item(i, self.lang) for i in _items(payload)]
