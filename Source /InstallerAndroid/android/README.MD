# VRChat OSC Banner — Android (Termux)
**by adam77461**

Control your VRChat chatbox from your Android phone. Runs a local web UI in your browser via Flask — no PC required. Auto-detects your VRChat headset on the network, supports Spotify, rotating captions, live clock, and all the same features as the PC/Mac version.

---

## Requirements

- Android phone with **[Termux](https://f-droid.org/packages/com.termux/)** installed
  - ⚠️ Install from **F-Droid only** — the Google Play version is outdated and broken
- Your phone and VRChat headset/PC on the **same Wi-Fi network**
- VRChat with OSC enabled

---

## Install

Open Termux and run:

```bash
curl -fsSL https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/android/install-termux.sh | bash
```

The installer will:
1. Request storage permission
2. Update Termux packages
3. Install Python, pip, nmap, and iproute2
4. Install Flask, python-osc, and requests
5. Download the app files from GitHub
6. Create a launcher and `vrchat-banner` shortcut command

---

## Launch

After installing, type in Termux:

```bash
vrchat-banner
```

Then open your Android browser and go to:

```
http://127.0.0.1:5000
```

The app will try to open your browser automatically. If it doesn't, copy the URL manually.

---

## Enable OSC in VRChat

Before using the app, enable OSC on your headset or PC:

> **Action Menu → Options → OSC → Enable**

---

## Features

### 🔍 Auto-Detect VRChat Headset
Tap **Auto-Detect** in the Target section. The app scans your entire local network subnet, pings every host, and checks for port 9000 (VRChat's OSC port). Devices with the OSC port open are highlighted in green — tap one to select it instantly.

### 💬 Rotating Captions
Add any text captions to rotate through your chatbox. Supports:
- Free text messages
- `{time}` — displays the live current date and time

### 🎵 Spotify Integration
- Login with Spotify using secure PKCE OAuth (no client secret needed)
- Auto-detects what's playing and displays it in VRChat
- Manual track entry for Spotify Free accounts (Premium required for API)
- 4-minute banner timer with auto-renewal if the song keeps playing
- Switches automatically when the song changes
- Removes itself cleanly when playback stops

### ⏱ Adjustable Interval
Control how fast captions rotate — 1 to 15 seconds.

### 💾 Persistent Captions
Your caption list saves to `captions.json` automatically and reloads on next launch.

---

## How the Spotify Banner Works

Once a song is added to the banner:

| Event | What happens |
|---|---|
| Song detected | Sends to VRChat immediately |
| Every 30 seconds | Re-sends to keep chatbox alive |
| Song changes | Switches to new song, resets timer |
| Playback stops | Removes itself automatically |
| After 4 minutes | Renews if same song still playing |

---

## Files

| Location | Contents |
|---|---|
| `~/vrchat-osc-banner/app/main.py` | Flask app |
| `~/vrchat-osc-banner/app/templates/index.html` | Web UI |
| `~/vrchat-osc-banner/app/captions.json` | Saved captions (auto-created) |
| `~/vrchat-osc-banner/app/spotify_token.json` | Spotify session cache (auto-created) |
| `~/vrchat-osc-banner/launch.sh` | Launcher script |
| `~/vrchat-osc-banner/uninstall.sh` | Uninstaller |

---

## Uninstall

```bash
bash ~/vrchat-osc-banner/uninstall.sh
```

Removes all files and the `vrchat-banner` alias.

---

## Troubleshooting

**"Command not found: vrchat-banner" after install**
Restart Termux or run `source ~/.bashrc`, then try again.

**Browser doesn't open automatically**
Open your Android browser manually and go to `http://127.0.0.1:5000`.

**Auto-detect finds nothing**
- Make sure your phone and headset are on the same Wi-Fi network
- Check that OSC is enabled in VRChat
- Try entering the IP manually — find it in your headset's Wi-Fi settings

**VRChat isn't receiving messages**
- Confirm the IP is correct
- Make sure port 9000 isn't blocked by your router
- Verify OSC is enabled in VRChat

**Spotify shows "403 — Premium required"**
The Spotify Web API requires a Premium account to read currently-playing tracks. Use the manual Artist + Song entry fields instead.

**App stops when Termux is minimized**
Termux may get killed by Android's battery optimization. To fix:
> Android Settings → Apps → Termux → Battery → Unrestricted

Or use a Termux:Widget or wake lock to keep it running.

**pkg install fails**
```bash
pkg update
pkg upgrade
```
Then retry the installer.

---

## One-liner reinstall

If something goes wrong, nuke and reinstall cleanly:

```bash
rm -rf ~/vrchat-osc-banner && curl -fsSL https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/android/install-termux.sh | bash
```

---

## Source

**[github.com/adam77461/OSC-Banner-for-vrchat](https://github.com/adam77461/OSC-Banner-for-vrchat)**

*Made by **adam77461***