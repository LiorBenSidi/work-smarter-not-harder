# Android APK / TWA Packaging

The Progressive Web App at **https://app.worksmarternotharder.dev** is wrapped as an
Android app using a **Trusted Web Activity (TWA)** — a thin native shell that loads the
live PWA URL fullscreen. The app auto-reflects every deploy (it loads the live URL; the
`no-store` shell keeps it fresh — no re-packaging needed on future deploys).

Generated with [PWABuilder](https://pwabuilder.com) → enter the site URL → **Package For
Stores** → **Android** → **Other Android** tab → *Download Package*.

> Use the **Other Android** tab (produces a directly installable, signed `.apk` + an
> Android Studio project) — not the *Google Play* tab (produces an `.aab` bundle intended
> for Play Store upload, not for a local run).

## Package settings

All values pull from the live web manifest (`web/static/manifest.webmanifest`); they are
already correct out of the box.

| Setting | Value | Source |
|---|---|---|
| **Package ID** | `dev.worksmarternotharder.app.twa` | chosen (reverse-domain) |
| **App name** | `Work Smarter, Not Harder` | manifest `name` |
| **Short name** | `Work Smarter` | manifest `short_name` |
| **Host** | `app.worksmarternotharder.dev` | deploy FQDN |
| **Start URL** | `/` | manifest `start_url` |
| **Version** | `1.0.0.0` | first build |
| **Version code** | `1` | first build |
| **Theme color** | `#0a0e20` | manifest `theme_color` |
| **Theme dark color** | `#0a0e20` | manifest `theme_color` |
| **Background color** | `#0a0e20` | manifest `background_color` |
| **Nav color** | `#0a0e20` | matches theme |
| **Nav dark color** | `#0a0e20` | matches theme |
| **Nav divider color** | `#0a0e20` | matches theme |
| **Nav divider dark color** | `#0a0e20` | matches theme |
| **Icon URL** | `https://app.worksmarternotharder.dev/static/icon-512.png` | manifest `icons` |
| **Maskable icon URL** | `https://app.worksmarternotharder.dev/static/icon-maskable-512.png` | manifest `icons` (maskable) |
| **Monochrome icon URL** | *(blank — no asset; placeholder text only)* | optional, skip |
| **Manifest URL** | `https://app.worksmarternotharder.dev/manifest.webmanifest` | live manifest |
| **Splash fade out duration** | `300` ms | default |
| **Settings shortcut** | Enabled | default (harmless long-press shortcut) |
| **Include source code** | Disabled | not needed for a local run |
| **Display mode** | Standalone | manifest `display` |
| **Meta Quest compatible** | Disabled | phone target |
| **Fallback behavior** | Custom Tabs | recommended; used only until Digital Asset Links verify |

## Fullscreen: Digital Asset Links

Until the site serves a matching `assetlinks.json`, the TWA falls back to **Custom Tabs**
(a Chrome tab with a visible URL bar). To go fullscreen, the site must serve
`/.well-known/assetlinks.json` containing the APK's signing certificate SHA-256 fingerprint.

1. Open `assetlinks.json` from the downloaded PWABuilder zip — copy the **SHA-256
   fingerprint** and confirm the **Package ID** (`dev.worksmarternotharder.app.twa`).
2. Serve it from Flask at `/.well-known/assetlinks.json` (see `web/app.py`, mirroring the
   `/manifest.webmanifest` `send_from_directory` route).
3. Deploy. Android re-verifies the link on next launch → URL bar disappears → fullscreen.

Once deployed, this holds for every future deploy (the fingerprint is tied to the signing
key, not the app content).

## Running locally in Android Studio

- **Fastest:** drag the signed `.apk` from the zip onto a running emulator / connected
  device (`adb install <file>.apk`).
- **From source:** open the extracted project folder in Android Studio → let Gradle sync →
  Run ▶ on an emulator or device.

## Notes

- The signing keystore is inside the downloaded zip — **keep it** (needed to publish future
  updates under the same Package ID). Do **not** commit it to the repo.
- Bump **Version** + **Version code** for each new store release (irrelevant for local runs).
