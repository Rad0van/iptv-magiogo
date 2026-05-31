# plugin.video.magiogo — Kodi add-on

A Kodi **video add-on** for Magio GO: browse Live TV and VOD (movies, series,
documentaries) as `plugin://` folders and play them. Reuses the shared
`src/core` package (single source of truth).

## Status

Works as a video add-on **and** integrates with Kodi's native Live TV guide:

- **Live TV** (Video Add-ons) → channel list → play (inputstream.ffmpegdirect)
- **VOD** → mirrors the app's **Magio Kino** exactly: the tabs (Dokumenty, Šport, …) and carousels are read live from 24i Backstage CMS (`/menus`, `/pages/{id}`), each row resolved from its `playlistId`. Series → seasons/episodes; play via inputstream.ffmpegdirect. Plus a Search. Falls back to raw categories if the CMS is unreachable.
- **Native TV guide (PVR)** → *Set up Live TV guide (PVR)* generates an M3U
  (channels via `plugin://` callbacks) + XMLTV EPG into the add-on profile and
  points `pvr.iptvsimple`'s instance settings at them. **Restart Kodi** to load
  the channels (the add-on never toggles the PVR client — doing so mid-run
  crashes Kodi). A background **service** keeps the EPG refreshed; iptvsimple
  re-reads the files on its own refresh interval. Catchup is wired via the EPG.
- Auth via add-on settings; titles needing another subscription are shown in
  **red** (red label everywhere; with the optional skin patch below, a red
  padlock on locked items and a red folder on fully-locked folders)
- **My devices** menu — lists the devices registered to your account; remove one
  via its context menu (long-press / `c`) → *Remove device*
- Device identity in settings: **Device name** (default hostname), **Device ID**
  (auto-generated unique `dsid`, persisted), **Device type** (`OTT_IPAD`, or
  `OTT_TV_ANDROID` for a big-screen device)
- Validated end-to-end against the live API (channels, VOD, M3U/EPG generation,
  pvr.iptvsimple config).

### Using the native TV guide

Open the add-on → **Set up Live TV guide (PVR)** once, then **restart Kodi**.
Channels + EPG appear in Kodi's **TV** section. The service refreshes the guide
periodically; toggle it in the add-on's *Live TV (PVR)* settings. Requires the
*PVR IPTV Simple Client* (auto-installed as a dependency).

## Features

- Live TV + VOD browsing/playback, native TV guide (PVR), catchup
- **VOD search** (VOD → *Search…*)
- Settings: credentials, content language, hide-unentitled, EPG days
- Friendly errors (prompts to open settings when credentials are missing/wrong)
- Branded icon/fanart (the MAGIO TV logo, extracted from the official app)

## Optional: red lock indicator in Estuary

Locked titles always show in **red text**. To also get a **red padlock** on
locked playable items and a **red folder** on fully-locked folders, run:

```bash
bash scripts/patch_estuary_lock.sh   # then restart Kodi
```

This covers both **list** views (List/WideList — the row glyph becomes the red
folder/padlock) and **poster/wall** views (Poster/Wall/InfoWall — a red badge
in the poster corner).

Estuary's views draw a fixed glyph / the poster and ignore an add-on's custom
icon, and Kodi's built-in "locked" overlay is overwritten by the watched-state
thumb-loader — so this installs a *user-space* copy of Estuary that reads the
add-on's `ParentalLocked` property (which does survive). Re-run it after a Kodi
update (a newer bundled Estuary would otherwise take over); remove it by
deleting `~/.kodi/addons/skin.estuary` and restarting Kodi.

## Device management

Each install identifies itself to Magio as one **device** (Settings → *Account*):

- **Device name** — the label shown in your account; defaults to the machine's
  hostname.
- **Device ID** — the `dsid`. Generated once as a unique value and persisted on
  first run (blank = auto), so every install is a *distinct* device instead of
  sharing one hard-coded id. Changing it registers a new device (uses a slot).
- **Device type** — `OTT_IPAD` (mobile/tablet, default) or `OTT_TV_ANDROID`
  (big screen / Android TV). **Big-screen requires a subscription that allows
  it:** on mobile-only packages (e.g. *Magio TV Štart*) an `OTT_TV_ANDROID`
  login is rejected — you'd need *Magio TV cez internet* (M / L / XL).

**My devices** (add-on root) lists the devices registered to your account, marks
the current one, and shows the free-slot counts per category. Remove a device
from its context menu (long-press / `c` → *Remove device*).

### Sharing one slot across machines

To let two installs (e.g. an HTPC and a laptop) count as the **same** device and
share a single slot, they must match on **both** the *Device ID* (`dsid`) **and**
the *Device name* — Magio keys a device on the `(dsid + name)` pair, so the same
`dsid` under a different name registers as a *separate* device that needs its own
slot.

**Copying the settings is not enough — also clear the saved token.** A login is
persisted to `.magio_token.json` (in the add-on profile dir) and is bound to the
device identity it was created with. The add-on only *refreshes* that token on
later runs and never re-sends the device name/`dsid`, so editing the settings
afterwards has no effect — you'll still authenticate as the old device and, once
the account is at its device limit, every channel fails with *"This content is
not available for you"* (the server's real error is `BENEFIT_DEVICE_MAX_LIMIT`).

After changing *Device ID* or *Device name* to match another install, **delete
`.magio_token.json`** so the next launch does a fresh login and rebinds to the
shared device. Confirm via **My devices**: the current device should show as
*registered*.

## Build & install (single zip)

```bash
bash scripts/build_addon.sh        # syncs src/core + vendors xmltv/roman, makes the zip
```

Then in Kodi: *Add-ons → Install from zip file →*
`addon/plugin.video.magiogo.zip`, open the add-on, and set your Magio GO
username/password in its settings.

## Install via the repository (auto-updates)

The repository is hosted on GitHub Pages and rebuilt automatically on every push
to `main` (see `.github/workflows/pages.yml`):

> **https://rad0van.github.io/iptv-magiogo/**

In Kodi, one-time setup:
1. *Settings → File manager → Add source* →
   `https://rad0van.github.io/iptv-magiogo/` (name it e.g. `magiogo`), **or**
   download
   [`repository.magiogo-1.0.0.zip`](https://rad0van.github.io/iptv-magiogo/repository.magiogo/repository.magiogo-1.0.0.zip).
2. *Add-ons → Install from zip file →* the `repository.magiogo` zip.
3. *Add-ons → Install from repository → Magio GO Repository →
   Video add-ons → Magio GO*.

Kodi then keeps `plugin.video.magiogo` updated automatically from Pages.

To rebuild/host locally instead: `bash scripts/build_repo.sh [BASE_URL]`
(defaults to the Pages URL) and serve `dist/`.

`resources/lib/core`, `resources/lib/xmltv.py`, `resources/lib/roman.py` and the
zip are generated by the build script and git-ignored. `requests` is provided by
`script.module.requests` at runtime; `inputstream.adaptive` /
`inputstream.ffmpegdirect` handle playback.

## Troubleshooting

### Kodi crashes when playback starts or stops

This is a **Kodi/ffmpeg audio-engine bug on some Linux builds** (seen on Asahi
Linux / Mesa GLES, Ubuntu 25.10, ffmpeg 7.1), **not** the add-on — the crash is
in `CActiveAE` → `swr_init`/`av_log` while (re)initializing the audio sink for
GUI sounds on playback start/stop. Two Kodi audio settings avoid it:

- **Settings → System → Audio → GUI sounds → `Off`**
  (`audiooutput.guisoundmode = 0`)
- **Settings → System → Audio → Keep audio device alive → `Always`**
  (`audiooutput.streamsilence`; the stored value for "Always" is the sentinel
  `153722867`)

With both set, VOD/live play and stop cleanly. These are Kodi settings (stored
in `userdata/guisettings.xml`), independent of this add-on.
