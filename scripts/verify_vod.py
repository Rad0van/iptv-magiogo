#!/usr/bin/env python3
"""Confirm the reverse-engineered Magio GO VOD API against a live account.

The VOD support in ``core/vod.py`` was built from the decompiled Android app and
contains assumptions marked ``UNVERIFIED`` (exact JSON field names, the VOD
stream-url id/drm params, and which response field holds the DRM license URL).
This script hits the real endpoints read-only, prints the actual shapes, runs
our parser, and tells you which guesses matched so the mappings can be fixed.

Usage:
    MAGIO_USERNAME=... MAGIO_PASSWORD=... python scripts/verify_vod.py

Nothing here writes to your account (GET only), except refreshing the auth token.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from core import Config, MagioClient, VodClient, kodi_inputstream_props  # noqa: E402
from core.vod import _items  # noqa: E402


def jdump(obj, n=1200):
    s = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    return s if len(s) <= n else s[:n] + "\n  ...(truncated)"


def report_mapping(label, items, mapped):
    print(f"\n  parsed {len(mapped)} {label}")
    if not items:
        return
    raw0 = items[0]
    m0 = mapped[0]
    print("  first raw item keys:", list(raw0.keys()))
    print("  mapped VodItem:", {k: v for k, v in m0.__dict__.items() if k != "raw"})
    missing = [f for f in ("title", "id", "type") if not getattr(m0, f)]
    if missing:
        print("  ⚠️  UNVERIFIED fields still empty (fix parse_item key order):", missing)


def main():
    user = os.environ.get("MAGIO_USERNAME")
    pw = os.environ.get("MAGIO_PASSWORD")
    if not user or not pw:
        print("Set MAGIO_USERNAME and MAGIO_PASSWORD in the environment.")
        return 2

    cfg = Config(username=user, password=pw,
                 token_path=os.path.join(ROOT, ".magio_token.json"))
    c = MagioClient(cfg)

    ok, access = c._refresh_tokens()
    if not ok or not access:
        a, r = c.login()
        if not a:
            print("AUTH FAILED — refresh token rejected and login failed. "
                  "Check the username/password.")
            return 1
        c._save_tokens(a, r)
    print("auth: OK")

    v = VodClient(c)

    # --- taxonomy ---
    print("\n=== /vod/categories ===")
    cpayload, cats = v.categories()
    for cat in cats[:5]:
        print(f"  id={cat['id']:>4}  {cat['name']!r}  genres={len(cat['genres'])}")

    print("\n=== /vod/genres ===")
    _gp, gens = v.genres()
    for g in gens[:5]:
        print(f"  id={g['id']:>4}  key={g['key']!r}  name={g['name']!r}")

    # --- movies ---
    print("\n=== /vod/movies type==MOVIE (limit 3) ===")
    payload, movies = v.movies(filter="type==MOVIE", limit=3)
    report_mapping("movies", _items(payload), movies)

    # --- series + episodes ---
    print("\n=== /vod/series (limit 3) ===")
    spayload, series = v.series(limit=3)
    report_mapping("series", _items(spayload), series)
    if series:
        s0 = series[0]
        print(f"  series {s0.id!r} {s0.title!r}  seasons={s0.season_count} episodes={s0.episode_count}")
        ep_payload, eps = v.episodes(serie_id=s0.id, limit=5)
        print(f"  episodes via serieId: got {len(eps)} ->",
              [(e.season_no, e.episode_no, e.id, e.title) for e in eps])

    # --- stream resolution (expect signed HLS, NO DRM) ---
    if movies:
        mid = movies[0].id
        print(f"\n=== stream-url service=VOD id={mid} ===")
        s = v.get_stream(mid)
        print("  success:", s.success, "| error:", s.error)
        print("  url:", (s.url or "")[:110])
        print("  manifest_type:", s.manifest_type, "| drm_scheme:", s.drm_scheme,
              "| license_url:", s.license_url)
        print("  kodi props:", jdump(kodi_inputstream_props(s), 600))
        if s.success and not s.url:
            print("  ⚠️  success but no URL — check the id/service params.")
        if s.license_url:
            print("  ℹ️  license URL present — this title is DRM-protected (unusual).")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
