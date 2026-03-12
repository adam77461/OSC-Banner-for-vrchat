import multiprocessing
multiprocessing.freeze_support()

import sys
import os

# Fix for PyInstaller on macOS — resolve bundled asset paths
def resource_path(relative_path):
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.abspath("."), relative_path)

# Fix customtkinter asset path when frozen
if hasattr(sys, '_MEIPASS'):
    import customtkinter
    customtkinter.set_widget_scaling(1.0)
    os.environ["CUSTOMTKINTER_ASSETS"] = resource_path("customtkinter")

import json
import threading
import time
import webbrowser
import urllib.parse
import urllib.request
import hashlib
import base64
import secrets as _secrets
import http.server
import socketserver
import socket as socket_module
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog
from pythonosc.udp_client import SimpleUDPClient


# ---------------- CONFIG ----------------
VRCHAT_IP = "127.0.0.1"
VRCHAT_PORT = 9000
DEFAULT_FILE = "captions.json"
TOKEN_FILE = "spotify_token.json"

SPOTIFY_CLIENT_ID = "690ecc75dfae468e9e8dc3a4697609fc"
# No client secret needed — using PKCE flow (safe to deploy publicly)
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_SCOPE = "user-read-currently-playing user-read-playback-state"

# Discord OAuth — PKCE flow, no client secret needed
# Enable PUBLIC_OAUTH2_CLIENT flag in Discord Developer Portal -> OAuth2
DISCORD_CLIENT_ID    = "1479680460979310727"
DISCORD_REDIRECT_URI = "http://127.0.0.1:8889/callback"
DISCORD_SCOPE        = "identify guilds guilds.members.read"
DISCORD_TOKEN_FILE   = "discord_token.json"

osc = SimpleUDPClient(VRCHAT_IP, VRCHAT_PORT)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ---------------- VERSION ----------------
APP_VERSION = "1.0.0"
VERSION_URL  = "https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/version.txt"
UPDATE_URL   = "https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/Source%20/main.py"

def check_for_update(silent=False):
    """Fetch version.txt from GitHub and compare to APP_VERSION."""
    try:
        req = urllib.request.Request(VERSION_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=5) as r:
            latest = r.read().decode().strip()
        if latest != APP_VERSION:
            return latest   # update available
        if not silent:
            app.after(0, lambda: update_status_label.configure(
                text=f"✓ Up to date (v{APP_VERSION})", text_color=SUCCESS))
        return None
    except Exception as e:
        if not silent:
            app.after(0, lambda: update_status_label.configure(
                text="Could not check for updates", text_color=TEXT_MUTED))
        return None

def do_update(latest_version):
    """Download new main.py, replace current file, restart."""
    try:
        app.after(0, lambda: update_btn.configure(text="Downloading...", state="disabled"))
        app.after(0, lambda: update_status_label.configure(
            text=f"Downloading v{latest_version}...", text_color=ACCENT))

        this_file = os.path.abspath(__file__)
        backup    = this_file + ".bak"

        # Download new version
        req = urllib.request.Request(UPDATE_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=15) as r:
            new_code = r.read()

        # Backup current file
        import shutil
        shutil.copy2(this_file, backup)

        # Write new file
        with open(this_file, "wb") as f:
            f.write(new_code)

        app.after(0, lambda: update_status_label.configure(
            text=f"✓ Updated to v{latest_version} — restarting...", text_color=SUCCESS))
        app.after(1500, _restart_app)

    except Exception as e:
        app.after(0, lambda: update_status_label.configure(
            text=f"Update failed: {e}", text_color=DANGER))
        app.after(0, lambda: update_btn.configure(text="Retry Update", state="normal"))

def _restart_app():
    save_geometry()
    import subprocess
    subprocess.Popen([sys.executable, os.path.abspath(__file__)])
    app.destroy()

def on_update_btn():
    """Legacy — now handled inside settings popup."""
    open_settings()

def auto_check_update():
    """Silently check on startup — show badge on settings gear if update available."""
    def _check():
        latest = check_for_update(silent=True)
        if latest:
            # Flash the settings button to hint update available
            app.after(0, lambda: settings_btn.configure(
                text="⚙✦", text_color=ACCENT))
    threading.Thread(target=_check, daemon=True).start()

running = False
captions = []
current_file = DEFAULT_FILE
selected_index = None

# Spotify state
spotify_token = None
spotify_refresh_token = None
spotify_token_expiry = 0
spotify_enabled = False
spotify_now_playing = ""
spotify_in_banner = False
spotify_send_running = False
_auth_code_holder = [None]

# Discord state
discord_token          = None
discord_refresh_token  = None
discord_token_expiry   = 0
discord_enabled        = False
discord_in_banner      = False
discord_banner_running = False
discord_status         = ""        # online/idle/dnd/offline
discord_username       = ""
discord_guild          = ""        # current server name
discord_voice_channel  = ""        # current voice channel
discord_last_dm        = ""        # last DM received
_discord_pkce_verifier = None
_discord_auth_holder   = [None]
_discord_auth_cancel   = [False]   # set True to abort a waiting auth thread


# Shared source preference — "spotify" or "discord"
active_source = "last_used"        # overwritten from settings file

# Style state lives in the Style tab composer (local to UI)
SETTINGS_FILE = "settings.json"

def load_settings():
    global active_source, VRCHAT_IP, VRCHAT_PORT
    try:
        with open(SETTINGS_FILE) as f:
            d = json.load(f)
        active_source = d.get("active_source", "spotify")
        VRCHAT_IP     = d.get("vrchat_ip", "127.0.0.1")
        VRCHAT_PORT   = int(d.get("vrchat_port", 9000))
    except:
        active_source = "spotify"
        VRCHAT_IP     = "127.0.0.1"
        VRCHAT_PORT   = 9000

def save_settings():
    try:
        with open(SETTINGS_FILE, "w") as f:
            json.dump({
                "active_source": active_source,
                "vrchat_ip":     VRCHAT_IP,
                "vrchat_port":   VRCHAT_PORT,
            }, f, indent=2)
    except:
        pass

load_settings()


def reconnect_osc(ip, port):
    global osc
    osc = SimpleUDPClient(ip, int(port))

# macaddress.io API key — used to look up vendor from MAC address
MACADDRESS_IO_KEY = "at_cIcDUDbhpdjE8q99w7D9ajapAS8ig"

# Fallback static OUI list in case API is unavailable
META_OUIS = {
    "2c:26:17", "48:05:60", "50:99:03", "78:c4:fa",
    "80:f3:ef", "84:57:f7", "88:25:08", "94:f9:29",
    "b4:17:a8", "c0:dd:8a", "cc:a1:74", "d0:b3:c2", "d4:d6:59",
}

_vendor_cache = {}  # ip -> vendor string, avoid re-querying

def lookup_mac_vendor(mac):
    """Look up vendor name via macaddress.io API."""
    if mac in _vendor_cache:
        return _vendor_cache[mac]
    try:
        url = f"https://api.macaddress.io/v1?apiKey={MACADDRESS_IO_KEY}&output=json&search={mac}"
        req = urllib.request.Request(url, headers={"User-Agent": "VRChatOSCBanner/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            data = json.loads(r.read())
        vendor = data.get("vendorDetails", {}).get("companyName", "")
        _vendor_cache[mac] = vendor
        print(f"[MAC] {mac} -> {vendor}")
        return vendor
    except Exception as e:
        print(f"[MAC] Lookup failed for {mac}: {e}")
        return ""

def is_meta_device(mac):
    """Return True if MAC belongs to Meta/Oculus via API or fallback OUI list."""
    vendor = lookup_mac_vendor(mac)
    if vendor:
        v = vendor.lower()
        return any(k in v for k in ("meta", "oculus", "facebook"))
    # Fallback to static list
    oui = ":".join(mac.split(":")[:3]).lower()
    return oui in META_OUIS

def _get_arp_table():
    """Read ARP table to get IP->MAC mappings without root/admin."""
    import subprocess, re, platform
    arp_map = {}
    try:
        system = platform.system()
        if system == "Windows":
            out = subprocess.check_output("arp -a", shell=True).decode(errors="ignore")
            for line in out.splitlines():
                m = re.search(r"(\d+\.\d+\.\d+\.\d+)\s+([\da-fA-F\-]{17})", line)
                if m:
                    ip  = m.group(1)
                    mac = m.group(2).replace("-", ":").lower()
                    arp_map[ip] = mac
        else:  # macOS / Linux
            out = subprocess.check_output(["arp", "-a"], stderr=subprocess.DEVNULL).decode(errors="ignore")
            for line in out.splitlines():
                m = re.search(r"\((\d+\.\d+\.\d+\.\d+)\)\s+at\s+([\da-fA-F:]{17})", line)
                if m:
                    ip  = m.group(1)
                    mac = m.group(2).lower()
                    arp_map[ip] = mac
    except Exception as e:
        print(f"[Scan] ARP error: {e}")
    return arp_map

def _ping_subnet(subnet_base):
    """Ping sweep to populate ARP table."""
    import subprocess, platform
    system = platform.system()
    pinged = []
    for i in range(1, 255):
        ip = f"{subnet_base}.{i}"
        try:
            if system == "Windows":
                subprocess.Popen(
                    ["ping", "-n", "1", "-w", "100", ip],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                subprocess.Popen(
                    ["ping", "-c", "1", "-W", "1", ip],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            pinged.append(ip)
        except: pass
    return pinged

def scan_for_headset(callback):
    """Find Meta Quest headset on LAN using ARP + OUI matching."""
    import socket as _sock

    def _scan():
        app.after(0, lambda: callback("scanning", None))

        # Get local IP / subnet
        try:
            s = _sock.socket(_sock.AF_INET, _sock.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except:
            local_ip = "192.168.1.1"

        subnet_base = local_ip.rsplit(".", 1)[0]
        print(f"[Scan] Local IP: {local_ip}, subnet: {subnet_base}.0/24")

        # Step 1 — check existing ARP table first (fast)
        app.after(0, lambda: callback("progress", 10))
        arp = _get_arp_table()
        print(f"[Scan] ARP table: {len(arp)} entries")

        found = []
        app.after(0, lambda: callback("progress", 15))
        for ip, mac in arp.items():
            if is_meta_device(mac):
                print(f"[Scan] Quest found in ARP: {ip} ({mac})")
                found.append((ip, mac))

        if found:
            app.after(0, lambda f=found: callback("done", f))
            return

        # Step 2 — ping sweep to populate ARP, then re-check
        app.after(0, lambda: callback("progress", 20))
        print(f"[Scan] No Quest in ARP — pinging {subnet_base}.0/24...")
        _ping_subnet(subnet_base)

        # Wait for pings to complete and ARP to populate
        import time as _t
        for pct in range(25, 90, 5):
            _t.sleep(0.4)
            app.after(0, lambda p=pct: callback("progress", p))

        app.after(0, lambda: callback("progress", 90))
        arp2 = _get_arp_table()
        print(f"[Scan] ARP after ping: {len(arp2)} entries")

        for ip, mac in arp2.items():
            if ip not in [f for f, _ in found]:  # skip already found
                if is_meta_device(mac):
                    print(f"[Scan] Quest found after ping: {ip} ({mac})")
                    found.append((ip, mac))

        app.after(0, lambda f=found: callback("done", f))

    threading.Thread(target=_scan, daemon=True).start()


# ---------------- OSC ----------------
def caption_text(c):
    """Get raw text from a caption (str or dict)."""
    return c["text"] if isinstance(c, dict) else c

def caption_style(c):
    """Get style snapshot from caption, or None for global."""
    if isinstance(c, dict):
        return c.get("style", None)
    return None

def format_caption(text, style=None):
    """Format text using a style snapshot dict, or plain if None."""
    if style is None:
        return text  # no style — send raw

    bc  = style.get("border_char", "~")
    bon = style.get("border_on", False)
    pad = style.get("padding", 2)
    tf  = style.get("time_format", "none")
    pre = style.get("prefix", "")
    suf = style.get("suffix", "")
    tpl = style.get("template", "{text}")

    t = ""
    if tf == "12hr":       t = datetime.now().strftime("%I:%M %p").lstrip("0")
    elif tf == "24hr":     t = datetime.now().strftime("%H:%M")
    elif tf == "datetime": t = datetime.now().strftime("%b %d %H:%M")

    body = text.replace("{time}", t)
    result = tpl.replace("{text}", body).replace("{time}", t)
    result = result.replace("{prefix}", pre).replace("{suffix}", suf)
    if pre and pre not in result: result = pre + result
    if suf and suf not in result: result = result + suf
    result = result.strip()

    if not bon or not bc:
        return result
    padding = " " * pad
    middle  = padding + result + padding
    border  = bc * len(middle)
    return f"{border}\n{middle}\n{border}"

def send_caption(text, style=None):
    formatted = format_caption(text, style)
    osc.send_message("/chatbox/input", [formatted, True, False])


# ---------------- JSON ----------------
def load_json(file_path):
    global captions, current_file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            raw_caps = data.get("captions", [])
            # Support both old plain-string and new dict format
            captions = [c if isinstance(c, dict) else {"text": c, "style": None} for c in raw_caps]
        current_file = file_path
        refresh_list()
        update_counter()
    except:
        pass

def save_json():
    with open(current_file, "w", encoding="utf-8") as f:
        json.dump({"captions": captions}, f, indent=4, ensure_ascii=False)


# ---------------- SPOTIFY PKCE AUTH ----------------
# PKCE = Proof Key for Code Exchange
# No client secret required — safe to ship in public/compiled apps

_pkce_verifier = None
_auth_code_holder = [None]

def _generate_pkce_pair():
    """Generate a code_verifier and SHA-256 code_challenge per RFC 7636."""
    import base64, os as _os
    raw       = _os.urandom(32)
    verifier  = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    digest    = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge

def save_tokens():
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "access_token": spotify_token,
            "refresh_token": spotify_refresh_token,
            "expiry": spotify_token_expiry
        }, f)

def load_tokens():
    global spotify_token, spotify_refresh_token, spotify_token_expiry
    try:
        with open(TOKEN_FILE, "r") as f:
            data = json.load(f)
            spotify_token = data.get("access_token")
            spotify_refresh_token = data.get("refresh_token")
            spotify_token_expiry = data.get("expiry", 0)
        return True
    except:
        return False

def exchange_code_for_token(code):
    """Exchange auth code + PKCE verifier for tokens. No secret needed."""
    global spotify_token, spotify_refresh_token, spotify_token_expiry
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "code_verifier": _pkce_verifier,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
    spotify_token = result["access_token"]
    spotify_refresh_token = result.get("refresh_token")
    spotify_token_expiry = time.time() + result.get("expires_in", 3600) - 60
    save_tokens()

def refresh_access_token():
    """Refresh using PKCE refresh token — still no secret needed."""
    global spotify_token, spotify_token_expiry, spotify_refresh_token
    if not spotify_refresh_token:
        return False
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": spotify_refresh_token,
        "client_id": SPOTIFY_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
        spotify_token = result["access_token"]
        spotify_token_expiry = time.time() + result.get("expires_in", 3600) - 60
        # PKCE refresh tokens rotate — save the new one if provided
        if "refresh_token" in result:
            spotify_refresh_token = result["refresh_token"]
        save_tokens()
        return True
    except:
        return False

def ensure_token():
    if time.time() >= spotify_token_expiry:
        return refresh_access_token()
    return spotify_token is not None

def get_now_playing():
    if not ensure_token():
        app.after(0, lambda: spotify_status_label.configure(
            text="Token expired — re-login needed", text_color=DANGER))
        return None
    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/currently-playing",
        headers={"Authorization": f"Bearer {spotify_token}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            status = resp.status
            if status == 204:
                app.after(0, lambda: spotify_status_label.configure(
                    text="Connected — nothing playing right now", text_color=TEXT_MUTED))
                return None
            raw = resp.read()
            data = json.loads(raw)
            if data and data.get("is_playing") and data.get("item"):
                item = data["item"]
                artists = ", ".join(a["name"] for a in item["artists"])
                track = item["name"]
                return f"Now Playing: {artists} - {track}"
            elif data and not data.get("is_playing"):
                app.after(0, lambda: spotify_status_label.configure(
                    text="Connected — playback paused", text_color=TEXT_MUTED))
            return None
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()
        except:
            pass
        if e.code == 401:
            app.after(0, lambda: spotify_status_label.configure(
                text="401 — token invalid, re-login", text_color=DANGER))
        elif e.code == 403:
            app.after(0, lambda: spotify_status_label.configure(
                text="403 — Spotify Premium required for API", text_color=DANGER))
        elif e.code == 429:
            app.after(0, lambda: spotify_status_label.configure(
                text="Rate limited — slowing down", text_color=DANGER))
        else:
            app.after(0, lambda c=e.code: spotify_status_label.configure(
                text=f"HTTP {c} error from Spotify", text_color=DANGER))
        print(f"Spotify API error {e.code}: {body}")
        return None
    except Exception as e:
        app.after(0, lambda: spotify_status_label.configure(
            text=f"Network error — check connection", text_color=DANGER))
        print(f"Spotify request error: {e}")
        return None

class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _auth_code_holder[0] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='background:#111827;color:#f9fafb;"
                b"font-family:sans-serif;display:flex;align-items:center;"
                b"justify-content:center;height:100vh;margin:0'>"
                b"<h2>&#9835; Connected to Spotify! You can close this tab.</h2>"
                b"</body></html>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Auth failed.")
    def log_message(self, *args):
        pass

def start_auth_server(callback):
    def _run():
        # Allow address reuse so relaunching doesn't get "port in use"
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", 8888), _CallbackHandler) as httpd:
            httpd.socket.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
            httpd.handle_request()
        code = _auth_code_holder[0]
        if code:
            try:
                exchange_code_for_token(code)
                app.after(0, callback, True)
            except Exception as e:
                print(f"Token exchange failed: {e}")
                app.after(0, callback, False)
        else:
            app.after(0, callback, False)
    threading.Thread(target=_run, daemon=True).start()

def do_spotify_login():
    global _pkce_verifier
    _pkce_verifier, challenge = _generate_pkce_pair()
    _auth_code_holder[0] = None

    spotify_login_btn.configure(text="Waiting...", state="disabled")

    params = urllib.parse.urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPE,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    })
    url = f"https://accounts.spotify.com/authorize?{params}"
    webbrowser.open(url)
    start_auth_server(on_spotify_auth_complete)

def on_spotify_auth_complete(success):
    global spotify_enabled
    if success:
        spotify_enabled = True
        spotify_login_btn.configure(text="Connected!", fg_color="#166534", state="normal")
        spotify_status_label.configure(text="Authenticated via PKCE", text_color=SUCCESS)
        start_spotify_poller()
    else:
        spotify_login_btn.configure(text="Login with Spotify",
                                    fg_color=SPOTIFY_GREEN, state="normal")
        spotify_status_label.configure(text="Auth failed — try again", text_color=DANGER)


# ---------------- SPOTIFY BANNER ENGINE ----------------
# Tracks the active spotify caption lifecycle independently from the main loop
spotify_poll_running = False
spotify_banner_thread_running = False
spotify_caption_active = False       # True while song is being sent to VRChat
spotify_caption_sent_at = 0.0        # Timestamp when current song started sending
spotify_caption_text = ""            # The exact text currently being sent
SPOTIFY_SEND_DURATION = 240          # 4 minutes in seconds
SPOTIFY_CHECK_INTERVAL = 30          # Check validity every 30 seconds while active

def start_spotify_poller():
    global spotify_poll_running
    if not spotify_poll_running:
        spotify_poll_running = True
        threading.Thread(target=spotify_poll_loop, daemon=True).start()

def spotify_poll_loop():
    """Polls Spotify every 10s, updates the UI display only."""
    global spotify_now_playing
    # Poll immediately on start so user sees feedback right away
    while spotify_poll_running:
        track = get_now_playing()
        new_val = track or ""
        if new_val != spotify_now_playing:
            spotify_now_playing = new_val
            app.after(0, update_spotify_display, spotify_now_playing)
        elif new_val:
            # Still same song — just refresh display
            app.after(0, update_spotify_display, spotify_now_playing)
        time.sleep(10)

def update_spotify_display(text):
    if text:
        short = text if len(text) <= 46 else text[:43] + "..."
        spotify_track_label.configure(text=short, text_color=SPOTIFY_GREEN)
    else:
        spotify_track_label.configure(text="Nothing playing", text_color=TEXT_MUTED)

def toggle_spotify_banner():
    global spotify_in_banner, spotify_banner_thread_running
    spotify_in_banner = not spotify_in_banner
    if spotify_in_banner:
        spotify_banner_btn.configure(
            text="✓ In Banner",
            fg_color=SPOTIFY_GREEN, hover_color="#17a349",
            text_color="#000000"
        )
        # Start the dedicated spotify banner thread
        if not spotify_banner_thread_running:
            spotify_banner_thread_running = True
            threading.Thread(target=spotify_banner_loop, daemon=True).start()
    else:
        spotify_in_banner = False
        spotify_banner_thread_running = False
        spotify_banner_btn.configure(
            text="+ Add to Banner",
            fg_color=BORDER, hover_color="#4b5563",
            text_color=TEXT_PRIMARY
        )
        app.after(0, lambda: spotify_status_label.configure(
            text="Banner disabled", text_color=TEXT_MUTED))

def spotify_banner_loop():
    """
    Dedicated thread that:
    1. Watches for a valid song
    2. Sends it to VRChat for 4 minutes
    3. Every 30s checks if the song is still valid (same song still playing)
    4. If song changes → immediately switches to new song and resets timer
    5. If nothing playing after 4 min → removes itself silently
    """
    global spotify_caption_active, spotify_caption_sent_at, spotify_caption_text
    global spotify_now_playing, spotify_banner_thread_running

    while spotify_in_banner and spotify_banner_thread_running:
        current_track = spotify_now_playing

        if not current_track:
            # Nothing playing — wait and check again
            app.after(0, lambda: spotify_status_label.configure(
                text="Waiting for a song...", text_color=TEXT_MUTED))
            time.sleep(SPOTIFY_CHECK_INTERVAL)
            continue

        # New song detected or first run
        if current_track != spotify_caption_text:
            spotify_caption_text = current_track
            spotify_caption_sent_at = time.time()
            spotify_caption_active = True
            app.after(0, lambda t=current_track: _update_spotify_status_sending(t))

        # Send the caption now
        send_caption(spotify_caption_text)
        app.after(0, lambda t=spotify_caption_text: now_label.configure(
            text=f'"{t[:35]}..."' if len(t) > 38 else f'"{t}"'))

        # Wait in 30-second chunks, checking validity each time
        elapsed = 0
        while elapsed < SPOTIFY_SEND_DURATION and spotify_in_banner:
            time.sleep(SPOTIFY_CHECK_INTERVAL)
            elapsed += SPOTIFY_CHECK_INTERVAL

            # Re-check: is the same song still playing?
            latest = spotify_now_playing

            if not latest:
                # Song stopped — clear and exit active state
                spotify_caption_active = False
                spotify_caption_text = ""
                app.after(0, lambda: spotify_status_label.configure(
                    text="Song ended — removed from banner", text_color=TEXT_MUTED))
                app.after(0, lambda: now_label.configure(text="—"))
                break

            if latest != spotify_caption_text:
                # Song changed — break inner loop to re-enter outer loop with new song
                app.after(0, lambda t=latest: _update_spotify_status_sending(t))
                break

            # Same song still valid — update the countdown in UI
            remaining = SPOTIFY_SEND_DURATION - elapsed
            mins = int(remaining // 60)
            secs = int(remaining % 60)
            app.after(0, lambda m=mins, s=secs: spotify_status_label.configure(
                text=f"Sending — expires in {m}m {s:02d}s",
                text_color=SPOTIFY_GREEN))

            # Re-send to keep chatbox alive
            if spotify_caption_text:
                send_caption(spotify_caption_text)

        else:
            # 4 minutes elapsed with same song — check one final time
            if spotify_now_playing == spotify_caption_text:
                # Still playing! Reset timer and keep going
                spotify_caption_sent_at = time.time()
                app.after(0, lambda: spotify_status_label.configure(
                    text="Still playing — renewing for 4 more min",
                    text_color=SPOTIFY_GREEN))
            else:
                # Different or no song — remove
                spotify_caption_active = False
                spotify_caption_text = ""
                app.after(0, lambda: spotify_status_label.configure(
                    text="4min expired, song changed — removed",
                    text_color=TEXT_MUTED))
                app.after(0, lambda: now_label.configure(text="—"))

    spotify_banner_thread_running = False
    spotify_caption_active = False

def _update_spotify_status_sending(track):
    short = track if len(track) <= 40 else track[:37] + "..."
    spotify_status_label.configure(
        text=f"Sending: {short}", text_color=SPOTIFY_GREEN)

def use_manual_track():
    """Manually set now-playing text from the entry fields."""
    global spotify_now_playing
    artist = manual_artist_entry.get().strip()
    song = manual_song_entry.get().strip()
    if not song and not artist:
        return
    parts = []
    if artist:
        parts.append(artist)
    if song:
        parts.append(song)
    spotify_now_playing = "Now Playing: " + " - ".join(parts)
    update_spotify_display(spotify_now_playing)




# ═══════════════════════════════════════════════════════
# DISCORD INTEGRATION
# ═══════════════════════════════════════════════════════

def _discord_generate_pkce():
    import base64, os as _os
    # Exact method confirmed working — 32 urandom bytes -> base64url no padding
    raw       = _os.urandom(32)
    verifier  = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    digest    = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge

def discord_save_tokens():
    try:
        with open(DISCORD_TOKEN_FILE, "w") as f:
            json.dump({
                "access_token":  discord_token,
                "refresh_token": discord_refresh_token,
                "expiry":        discord_token_expiry
            }, f)
    except:
        pass

def discord_load_tokens():
    global discord_token, discord_refresh_token, discord_token_expiry
    try:
        with open(DISCORD_TOKEN_FILE) as f:
            d = json.load(f)
        discord_token         = d.get("access_token")
        discord_refresh_token = d.get("refresh_token")
        discord_token_expiry  = d.get("expiry", 0)
        return True
    except:
        return False

def discord_refresh():
    global discord_token, discord_token_expiry, discord_refresh_token
    if not discord_refresh_token:
        return False
    # Refresh using PKCE — no client_secret needed (PUBLIC_OAUTH2_CLIENT flag)
    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": discord_refresh_token,
        "client_id":     DISCORD_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        "https://discord.com/api/oauth2/token", data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "VRChatOSCBanner/1.0 (https://github.com/adam77461/OSC-Banner-for-vrchat)",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            res = json.loads(r.read())
        discord_token         = res["access_token"]
        discord_token_expiry  = time.time() + res.get("expires_in", 604800) - 60
        if "refresh_token" in res:
            discord_refresh_token = res["refresh_token"]
        discord_save_tokens()
        return True
    except:
        return False

def discord_ensure_token():
    if time.time() >= discord_token_expiry:
        return discord_refresh()
    return discord_token is not None

def discord_api(endpoint):
    """GET from Discord API with current token."""
    print(f"[Discord] API call: {endpoint}, token={'set' if discord_token else 'NONE'}, expiry={discord_token_expiry:.0f}, now={time.time():.0f}")
    if not discord_token:
        print(f"[Discord] No token — skipping API call")
        return None
    # Only refresh if token is actually expired (not on first call)
    if discord_token_expiry > 0 and time.time() >= discord_token_expiry:
        print(f"[Discord] Token expired, refreshing...")
        if not discord_refresh():
            return None
    req = urllib.request.Request(
        f"https://discord.com/api/v10{endpoint}",
        headers={
            "Authorization": f"Bearer {discord_token}",
            "User-Agent": "VRChatOSCBanner/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"[Discord] API {endpoint} HTTP {e.code}: {body}")
        app.after(0, lambda c=e.code: discord_status_label.configure(
            text=f"Discord API error {c}", text_color=DANGER))
        return None
    except Exception as ex:
        print(f"[Discord] API {endpoint} error: {ex}")
        return None

def discord_fetch_status():
    """Fetch user identity, guilds, voice state."""
    global discord_username, discord_status, discord_guild, discord_voice_channel
    # Identity
    me = discord_api("/users/@me")
    print(f"[Discord] /users/@me response: {me}")
    if not me:
        return
    discord_username = me.get("global_name") or me.get("username", "")
    # Guilds
    guilds = discord_api("/users/@me/guilds") or []
    print(f"[Discord] guilds count: {len(guilds)}")
    if guilds:
        discord_guild = guilds[0].get("name", "")
    print(f"[Discord] username={discord_username} guild={discord_guild}")
    _build_discord_banner_text()

def _build_discord_banner_text():
    """Assemble the text to send to VRChat from Discord info."""
    global discord_status
    parts = []
    if discord_username:
        parts.append(f"Discord: {discord_username}")
    if discord_guild:
        parts.append(f"In: {discord_guild}")
    if discord_voice_channel:
        parts.append(f"VC: {discord_voice_channel}")
    if discord_last_dm:
        parts.append(f"DM: {discord_last_dm[:30]}")
    discord_status = " | ".join(parts) if parts else ""
    if discord_status:
        app.after(0, lambda: discord_info_label.configure(
            text=discord_status[:60], text_color="#5865f2"))

class _DiscordCallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"[Discord] Callback hit: {self.path}")
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        print(f"[Discord] Parsed params: {params}")
        if "code" in params:
            _discord_auth_holder[0] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='background:#111827;color:#f9fafb;"
                b"font-family:sans-serif;display:flex;align-items:center;"
                b"justify-content:center;height:100vh;margin:0'>"
                b"<h2>&#128172; Connected to Discord! You can close this tab.</h2>"
                b"</body></html>"
            )
        else:
            print(f"[Discord] No code in params — sending 400")
            self.send_response(400)
            self.end_headers()
    def do_GET_favicon(self): pass
    def log_message(self, fmt, *args):
        print(f"[Discord HTTP] {fmt % args}")

# Hardcoded fallback URL (no PKCE challenge — use if browser doesn't open)
DISCORD_FALLBACK_URL = (
    "https://discord.com/oauth2/authorize"
    "?client_id=1479680460979310727"
    "&response_type=code"
    "&redirect_uri=http%3A%2F%2F127.0.0.1%3A8889%2Fcallback"
    "&scope=identify+guilds+guilds.members.read"
)

def _show_secret_prompt():
    """Prompt user to enter their Discord client secret — saved locally, never to GitHub."""
    win = ctk.CTkToplevel(app)
    win.title("Discord Client Secret")
    win.geometry("460x220")
    win.configure(fg_color=SURFACE)
    win.grab_set()

    ctk.CTkLabel(win, text="Enter your Discord Client Secret",
                 font=("Segoe UI", 13, "bold"), text_color=TEXT_PRIMARY).pack(pady=(18, 4))
    ctk.CTkLabel(win,
        text="Found at: discord.com/developers  >  Your App  >  OAuth2  |  Saved locally only, never uploaded.",
        font=("Segoe UI", 10), text_color=TEXT_MUTED, justify="center").pack(pady=(0, 10))

    secret_entry = ctk.CTkEntry(win, placeholder_text="Client Secret",
                                 font=("Consolas", 12), fg_color=CARD,
                                 border_color=BORDER, text_color=TEXT_PRIMARY,
                                 show="*", width=380, height=34)
    secret_entry.pack(padx=20)

    def save_and_login():
        global DISCORD_CLIENT_SECRET
        secret = secret_entry.get().strip()
        if not secret:
            return
        try:
            with open(DISCORD_SECRET_FILE, "w") as f:
                f.write(secret)
            DISCORD_CLIENT_SECRET = secret
            win.destroy()
            do_discord_login()
        except Exception as e:
            ctk.CTkLabel(win, text=f"Save failed: {e}", text_color=DANGER).pack()

    ctk.CTkButton(win, text="Save & Login", width=160, height=34,
                  fg_color=DISCORD_BLUE, hover_color="#4338ca",
                  font=("Segoe UI", 12, "bold"),
                  command=save_and_login).pack(pady=12)

def do_discord_login():
    global _discord_pkce_verifier
    # Cancel any previous auth attempt
    _discord_auth_cancel[0] = True
    _discord_auth_holder[0] = None
    time.sleep(0.15)  # let old thread notice cancel and exit
    _discord_auth_cancel[0] = False

    verifier, challenge = _discord_generate_pkce()
    _discord_pkce_verifier = verifier

    state = base64.urlsafe_b64encode(os.urandom(8)).rstrip(b"=").decode()
    params = urllib.parse.urlencode({
        "client_id":             DISCORD_CLIENT_ID,
        "response_type":         "code",
        "redirect_uri":          DISCORD_REDIRECT_URI,
        "scope":                 DISCORD_SCOPE,
        "code_challenge_method": "S256",
        "code_challenge":        challenge,
        "prompt":                "consent",
        "state":                 state,
    })
    auth_url = f"https://discord.com/oauth2/authorize?{params}"
    print(f"[Discord] Auth URL challenge={challenge}")

    discord_login_btn.configure(text="Authorizing...", state="disabled")
    discord_status_label.configure(
        text="Starting local server...", text_color=TEXT_MUTED)

    # ── Start server FIRST, then open browser ──
    # Use an event so we know the server is bound before the browser opens
    server_ready = threading.Event()

    def _run_server():
        # Force-close any lingering socket on 8889
        try:
            import socket as _sock
            killer = _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM)
            killer.setsockopt(_sock.SOL_SOCKET, _sock.SO_REUSEADDR, 1)
            killer.bind(("127.0.0.1", 8889))
            killer.close()
        except: pass

        socketserver.TCPServer.allow_reuse_address = True
        try:
            srv = socketserver.TCPServer(("127.0.0.1", 8889), _DiscordCallbackHandler)
            srv.socket.setsockopt(socket_module.SOL_SOCKET, socket_module.SO_REUSEADDR, 1)
            srv.timeout = 180
            print(f"[Discord] Callback server listening on 127.0.0.1:8889")
            server_ready.set()   # signal: server is bound and ready
            # Keep serving until we get the code (handles favicon pre-requests)
            for _ in range(5):
                srv.handle_request()
                if _discord_auth_holder[0] is not None:
                    break
            srv.server_close()
            print(f"[Discord] Callback server closed, code={_discord_auth_holder[0]}")
        except Exception as e:
            print(f"[Discord] Server error: {type(e).__name__}: {e}")
            server_ready.set()   # unblock even on error

        # After request handled, do the token exchange
        _discord_exchange(verifier)

    threading.Thread(target=_run_server, daemon=True).start()

    # Wait up to 2s for server to be ready, then open browser
    def _open_browser():
        if not server_ready.wait(timeout=2.0):
            print("[Discord] Server took too long to start")
        opened = False
        try:
            webbrowser.open(auth_url)
            opened = True
        except:
            pass
        if opened:
            app.after(0, lambda: discord_status_label.configure(
                text="Browser opened — authorize then return here",
                text_color=TEXT_MUTED))
        else:
            app.after(0, lambda: discord_status_label.configure(
                text="Browser didn't open — click Copy URL below",
                text_color=ACCENT))
            app.after(0, _show_fallback_url)

    threading.Thread(target=_open_browser, daemon=True).start()

def _show_fallback_url():
    """Show a copyable fallback URL dialog if browser didn't open."""
    import tkinter as tk
    win = ctk.CTkToplevel(app)
    win.title("Discord Login URL")
    win.geometry("520x180")
    win.configure(fg_color=SURFACE)
    win.grab_set()

    ctk.CTkLabel(win, text="Open this URL in your browser to authorize:",
                 font=("Segoe UI", 11), text_color=TEXT_MUTED).pack(pady=(16, 6))

    url_box = ctk.CTkEntry(win, font=("Consolas", 9), fg_color=CARD,
                            border_color=BORDER, text_color=TEXT_PRIMARY,
                            width=480, height=36)
    url_box.pack(padx=16)
    url_box.insert(0, DISCORD_FALLBACK_URL)
    url_box.configure(state="readonly")

    def copy_url():
        app.clipboard_clear()
        app.clipboard_append(DISCORD_FALLBACK_URL)
        copy_btn.configure(text="✓ Copied!")
        win.after(1500, lambda: copy_btn.configure(text="Copy URL"))

    copy_btn = ctk.CTkButton(win, text="Copy URL", width=120, height=30,
                              fg_color=ACCENT, hover_color="#1d4ed8",
                              font=("Segoe UI", 11, "bold"),
                              command=copy_url)
    copy_btn.pack(pady=10)

    ctk.CTkLabel(win, text="After authorizing in browser, close this window.",
                 font=("Segoe UI", 9), text_color=TEXT_MUTED).pack()

def _discord_exchange(verifier):
    """Exchange auth code for token — called after callback server receives the code."""
    global discord_token, discord_refresh_token, discord_token_expiry, discord_enabled
    code = _discord_auth_holder[0]
    print(f"[Discord] Code received (full): '{code}' len={len(code) if code else 0}")
    if _discord_auth_cancel[0]:
        print("[Discord] Auth cancelled — stale thread exiting")
        return
    if not code:
        app.after(0, lambda: discord_status_label.configure(
            text="Auth cancelled or timed out", text_color=DANGER))
        app.after(0, lambda: discord_login_btn.configure(
            text="Login with Discord", state="normal"))
        return
    try:
        # Exchange code using PKCE verifier passed directly from login function
        print(f"[Discord] Exchanging code with verifier={verifier} (len={len(verifier)})")
        print(f"[Discord] Code length: {len(code)}")
        # Build POST body manually — code_verifier must NOT be percent-encoded
        # urllib.parse.urlencode encodes - and _ which breaks Discord PKCE
        body_parts = [
            f"grant_type=authorization_code",
            f"code={urllib.parse.quote(code, safe='')}",
            f"redirect_uri={urllib.parse.quote(DISCORD_REDIRECT_URI, safe='')}",
            f"client_id={DISCORD_CLIENT_ID}",
            f"code_verifier={verifier}",  # verifier is already safe chars only
        ]
        data = "&".join(body_parts).encode("ascii")
        print(f"[Discord] POST body: {data.decode()}")
        req = urllib.request.Request(
            "https://discord.com/api/oauth2/token", data=data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "VRChatOSCBanner/1.0 (https://github.com/adam77461/OSC-Banner-for-vrchat)",
            }
        )
        # Flat try/except — HTTPError caught first with full body printed
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read()
            print(f"[Discord] Token response: {raw.decode()}")
            res = json.loads(raw)
        except urllib.error.HTTPError as http_err:
            body = http_err.read().decode()
            print(f"[Discord] Token exchange HTTP {http_err.code}")
            print(f"[Discord] Response headers: {dict(http_err.headers)}")
            print(f"[Discord] Response body: {body}")
            try:
                err_json = json.loads(body)
                msg = err_json.get("error_description") or err_json.get("error") or f"HTTP {http_err.code}"
            except:
                msg = f"HTTP {http_err.code}: {body[:80]}"
            app.after(0, lambda m=msg: discord_status_label.configure(
                text=f"Auth failed: {m}", text_color=DANGER))
            app.after(0, lambda: discord_login_btn.configure(
                text="Login with Discord", state="normal"))
            return
        except Exception as ex:
            print(f"[Discord] Request error: {type(ex).__name__}: {ex}")
            app.after(0, lambda m=str(ex): discord_status_label.configure(
                text=f"Request error: {m}", text_color=DANGER))
            app.after(0, lambda: discord_login_btn.configure(
                text="Login with Discord", state="normal"))
            return

        if "access_token" not in res:
            print(f"[Discord] Unexpected response: {res}")
            app.after(0, lambda: discord_status_label.configure(
                text=f"Bad response: {res.get('error', 'unknown')}", text_color=DANGER))
            app.after(0, lambda: discord_login_btn.configure(
                text="Login with Discord", state="normal"))
            return

        discord_token         = res["access_token"]
        discord_refresh_token = res.get("refresh_token")
        discord_token_expiry  = time.time() + res.get("expires_in", 604800) - 60
        discord_enabled       = True
        discord_save_tokens()
        print(f"[Discord] Login SUCCESS — token saved")
        def _on_success():
            try:
                discord_login_btn.configure(text="Connected!", fg_color="#3730a3", state="normal")
                discord_status_label.configure(text="Connected! Fetching profile...", text_color="#818cf8")
                discord_info_label.configure(text="Loading...", text_color="#818cf8")
            except Exception as ui_err:
                print(f"[Discord] UI update error: {ui_err}")
        app.after(0, _on_success)
        start_discord_poller()
    except Exception as e:
        import traceback
        print(f"[Discord] Exchange exception: {type(e).__name__}: {e}")
        traceback.print_exc()
        app.after(0, lambda err=str(e): discord_status_label.configure(
            text=f"Auth error: {err}", text_color=DANGER))
        app.after(0, lambda: discord_login_btn.configure(
            text="Login with Discord", state="normal"))

_discord_poll_running = [False]

def start_discord_poller():
    if not _discord_poll_running[0]:
        _discord_poll_running[0] = True
        threading.Thread(target=_discord_poll_loop, daemon=True).start()

def _discord_poll_loop():
    while _discord_poll_running[0]:
        discord_fetch_status()
        time.sleep(15)

def toggle_discord_banner():
    global discord_in_banner, discord_banner_running
    discord_in_banner = not discord_in_banner
    if discord_in_banner:
        discord_banner_btn.configure(
            text="✓ In Banner", fg_color="#4338ca",
            hover_color="#3730a3", text_color="#fff")
        if not discord_banner_running:
            discord_banner_running = True
            threading.Thread(target=_discord_banner_loop, daemon=True).start()
    else:
        discord_in_banner      = False
        discord_banner_running = False
        discord_banner_btn.configure(
            text="+ Add to Banner", fg_color=BORDER,
            hover_color="#4b5563", text_color=TEXT_PRIMARY)
        app.after(0, lambda: discord_status_label.configure(
            text="Banner disabled", text_color=TEXT_MUTED))

def _discord_banner_loop():
    global discord_banner_running
    while discord_in_banner and discord_banner_running:
        text = discord_status
        if text:
            send_caption(text)
            app.after(0, lambda t=text: discord_status_label.configure(
                text=f"Sending: {t[:40]}", text_color="#818cf8"))
        else:
            app.after(0, lambda: discord_status_label.configure(
                text="Waiting for Discord data...", text_color=TEXT_MUTED))
        time.sleep(30)
    discord_banner_running = False

# ---------------- MAIN CAPTION LOOP ----------------
current_caption_index = [0]
SPOTIFY_GREEN = "#1db954"

def loop():
    """Main loop — handles regular captions and {time}. Spotify runs its own thread."""
    global running
    while running:
        base = list(captions)

        if not base:
            time.sleep(0.5)
            continue

        idx = current_caption_index[0] % len(base)
        caption = base[idx]
        current_caption_index[0] = idx + 1

        raw   = caption_text(caption)
        style = caption_style(caption)
        if raw == "{time}":
            text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            text = raw

        app.after(0, lambda t=text, i=idx: update_now_sending(t, i))
        send_caption(text, style)
        time.sleep(delay_slider.get())

    app.after(0, lambda: now_label.configure(text="—"))


def update_now_sending(text, idx):
    display = text if len(text) <= 38 else text[:35] + "..."
    now_label.configure(text=f'"{display}"')
    if idx >= 0:
        highlight_row(idx)

def start_loop():
    global running
    if not running:
        running = True
        current_caption_index[0] = 0
        threading.Thread(target=loop, daemon=True).start()
        start_btn.configure(text="  Running", fg_color="#166534", hover_color="#14532d")
        stop_btn.configure(state="normal")
        pulse_status(True)

def stop_loop():
    global running
    running = False
    start_btn.configure(text="  Start", fg_color=ACCENT, hover_color="#1d4ed8")
    stop_btn.configure(state="disabled")
    pulse_status(False)


# ---------------- UI HELPERS ----------------
ACCENT = "#2563eb"
SURFACE = "#111827"
CARD = "#1f2937"
BORDER = "#374151"
TEXT_PRIMARY = "#f9fafb"
TEXT_MUTED = "#9ca3af"
SUCCESS = "#16a34a"
DANGER = "#dc2626"
HIGHLIGHT = "#1e3a5f"
SPOTIFY_GREEN = "#1db954"

row_frames = []

def refresh_list():
    global row_frames
    try:
        list_inner.winfo_children()
    except NameError:
        return  # UI not built yet
    for w in list_inner.winfo_children():
        w.destroy()
    row_frames.clear()

    for i, c in enumerate(captions):
        raw   = caption_text(c)
        style = caption_style(c)
        is_time   = "{time}" in raw
        is_styled = style is not None
        # show styled row if caption has own style OR global style is active
        show_preview = is_styled  # only show preview if caption has its own style

        row = ctk.CTkFrame(list_inner, fg_color=CARD, corner_radius=8,
                           height=54 if show_preview else 38)
        row.pack(fill="x", pady=2, padx=0)
        row.pack_propagate(False)
        row_frames.append(row)

        # Badge: 🎨 for own style, ⏰ for time, 💬 default
        icon = "🎨" if is_styled else ("⏰" if is_time else "💬")
        icon_color = "#a78bfa" if is_styled else TEXT_MUTED
        icon_lbl = ctk.CTkLabel(row, text=icon, font=("Segoe UI Emoji", 13),
                                 width=28, text_color=icon_color)
        icon_lbl.place(x=8, y=9, anchor="nw")

        display_text = raw if len(raw) <= 48 else raw[:45] + "..."
        text_lbl = ctk.CTkLabel(row, text=display_text, font=("Segoe UI", 12),
                                 text_color=TEXT_PRIMARY, anchor="w")
        text_lbl.place(x=36, y=7, anchor="nw")

        if show_preview:
            preview_str = format_caption(raw, style)
            preview_compact = preview_str.replace("\n", "  ").strip()
            if len(preview_compact) > 60:
                preview_compact = preview_compact[:57] + "..."
            preview_color = "#a78bfa" if is_styled else "#6b7280"
            preview_lbl = ctk.CTkLabel(row, text=preview_compact,
                font=("Consolas", 8), text_color=preview_color, anchor="w")
            preview_lbl.place(x=36, y=28, anchor="nw")

        del_btn = ctk.CTkButton(
            row, text="✕", width=24, height=24,
            font=("Segoe UI", 10, "bold"),
            fg_color="transparent", hover_color="#374151",
            text_color=TEXT_MUTED, corner_radius=6,
            command=lambda idx=i: delete_caption(idx)
        )
        del_btn.place(relx=1.0, x=-6, y=6, anchor="ne")

        for widget in [row, text_lbl, icon_lbl]:
            widget.bind("<Button-1>", lambda e, idx=i: select_row(idx))

    update_counter()

def highlight_row(idx):
    for i, f in enumerate(row_frames):
        f.configure(fg_color=HIGHLIGHT if i == idx else CARD)

def select_row(idx):
    global selected_index
    selected_index = idx
    highlight_row(idx)

def update_counter():
    count_label.configure(text=f"{len(captions)} captions")

def pulse_status(active):
    if active:
        status_dot.configure(text_color=SUCCESS)
        status_text.configure(text="Live", text_color=SUCCESS)
    else:
        status_dot.configure(text_color=DANGER)
        status_text.configure(text="Stopped", text_color=DANGER)

def add_caption():
    text = entry.get().strip()
    if text:
        captions.append({"text": text, "style": None})
        entry.delete(0, "end")
        refresh_list()
        save_json()
        list_scroll.after(50, lambda: list_scroll._parent_canvas.yview_moveto(1.0))

def delete_caption(idx):
    if 0 <= idx < len(captions):
        captions.pop(idx)
        refresh_list()
        save_json()

def load_file():
    file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
    if file_path:
        load_json(file_path)

def clear_all():
    captions.clear()
    refresh_list()
    save_json()

def on_entry_return(event):
    add_caption()

def update_delay_label(val):
    delay_val_label.configure(text=f"{float(val):.1f}s")

def apply_ip():
    global VRCHAT_IP, VRCHAT_PORT
    ip = ip_entry.get().strip()
    port_str = port_entry.get().strip()
    if not ip:
        ip_status.configure(text="IP required", text_color=DANGER)
        return
    try:
        port = int(port_str)
        if not (1 <= port <= 65535):
            raise ValueError
    except ValueError:
        ip_status.configure(text="Invalid port", text_color=DANGER)
        return
    try:
        VRCHAT_IP   = ip
        VRCHAT_PORT = port
        reconnect_osc(ip, port)
        save_settings()
        footer_target.configure(text=f"->  {ip}:{port}")
        ip_status.configure(text="Saved!", text_color=SUCCESS)
        app.after(2000, lambda: ip_status.configure(text=""))
    except Exception:
        ip_status.configure(text="Failed", text_color=DANGER)


def apply_target():
    """Called from settings popup — same as apply_ip."""
    apply_ip()


# ================================================================
# BUILD UI
# ================================================================
app = ctk.CTk()
app.title("VRChat OSC Banner")
app.resizable(True, True)
app.minsize(480, 600)
app.configure(fg_color=SURFACE)

# ── Restore saved window geometry ──
GEOMETRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window_geometry.txt")

def save_geometry():
    try:
        with open(GEOMETRY_FILE, "w") as f:
            f.write(app.geometry())
    except:
        pass

def load_geometry():
    try:
        with open(GEOMETRY_FILE, "r") as f:
            geo = f.read().strip()
        if geo:
            app.geometry(geo)
            return
    except:
        pass
    # Default: centre on screen at 560x820
    app.update_idletasks()
    sw = app.winfo_screenwidth()
    sh = app.winfo_screenheight()
    w, h = 560, 820
    x = (sw - w) // 2
    y = (sh - h) // 2
    app.geometry(f"{w}x{h}+{x}+{y}")

load_geometry()
app.protocol("WM_DELETE_WINDOW", lambda: (save_geometry(), app.destroy()))

# ── Settings Popup ──
def open_settings():
    win = ctk.CTkToplevel(app)
    win.title("Settings")
    win.geometry("420x520")
    win.configure(fg_color=SURFACE)
    win.grab_set()
    win.resizable(False, False)

    ctk.CTkLabel(win, text="⚙  Settings", font=("Segoe UI", 16, "bold"),
                 text_color=TEXT_PRIMARY).pack(pady=(18, 14))

    # ── Load JSON ──
    section = ctk.CTkFrame(win, fg_color=CARD, corner_radius=10)
    section.pack(fill="x", padx=20, pady=(0, 10))
    ctk.CTkLabel(section, text="CAPTIONS FILE", font=("Segoe UI", 9, "bold"),
                 text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 4))
    ctk.CTkButton(section, text="📂  Load JSON File", height=34,
                  font=("Segoe UI", 12), fg_color=BORDER, hover_color="#4b5563",
                  text_color=TEXT_PRIMARY, corner_radius=8,
                  command=lambda: (load_file(), win.focus())).pack(fill="x", padx=14, pady=(0, 10))

    # ── Clear All ──
    ctk.CTkButton(section, text="🗑  Clear All Captions", height=34,
                  font=("Segoe UI", 12), fg_color="transparent", hover_color="#374151",
                  text_color=DANGER, corner_radius=8, border_width=1, border_color="#7f1d1d",
                  command=lambda: (clear_all(), win.focus())).pack(fill="x", padx=14, pady=(0, 14))

    # ── VRChat Target ──
    tgt = ctk.CTkFrame(win, fg_color=CARD, corner_radius=10)
    tgt.pack(fill="x", padx=20, pady=(0, 10))
    ctk.CTkLabel(tgt, text="VRCHAT TARGET", font=("Segoe UI", 9, "bold"),
                 text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 4))
    tgt_row = ctk.CTkFrame(tgt, fg_color="transparent")
    tgt_row.pack(fill="x", padx=14, pady=(0, 12))
    _ip = ctk.CTkEntry(tgt_row, placeholder_text="IP Address",
                       font=("Consolas", 12), fg_color=SURFACE, border_color=BORDER,
                       border_width=1, text_color=TEXT_PRIMARY,
                       placeholder_text_color=TEXT_MUTED, width=170, height=30, corner_radius=6)
    _ip.insert(0, ip_entry.get())
    _ip.pack(side="left", padx=(0, 6))
    _port = ctk.CTkEntry(tgt_row, placeholder_text="Port",
                         font=("Consolas", 12), fg_color=SURFACE, border_color=BORDER,
                         border_width=1, text_color=TEXT_PRIMARY,
                         placeholder_text_color=TEXT_MUTED, width=80, height=30, corner_radius=6)
    _port.insert(0, port_entry.get())
    _port.pack(side="left", padx=(0, 6))
    def _apply_target():
        ip_entry.delete(0, "end"); ip_entry.insert(0, _ip.get())
        port_entry.delete(0, "end"); port_entry.insert(0, _port.get())
        apply_target()
        _apply_lbl.configure(text="✓ Saved", text_color=SUCCESS)
        tgt.after(2000, lambda: _apply_lbl.configure(text=""))
    ctk.CTkButton(tgt_row, text="Apply", width=64, height=30,
                  font=("Segoe UI", 11), fg_color=ACCENT, hover_color="#1d4ed8",
                  text_color="#fff", corner_radius=6,
                  command=_apply_target).pack(side="left", padx=(0,6))
    _apply_lbl = ctk.CTkLabel(tgt_row, text="", font=("Segoe UI", 10),
                               text_color=SUCCESS)
    _apply_lbl.pack(side="left")

    # ── Auto-find headset ──
    scan_row = ctk.CTkFrame(tgt, fg_color="transparent")
    scan_row.pack(fill="x", padx=14, pady=(0, 12))

    scan_status = ctk.CTkLabel(scan_row, text="Click to scan for VRChat headset on your network",
                                font=("Segoe UI", 9), text_color=TEXT_MUTED, anchor="w")
    scan_status.pack(side="left", expand=True, fill="x")

    found_hosts = []

    def _on_scan(state, data):
        if state == "scanning":
            scan_btn.configure(text="Scanning...", state="disabled")
            scan_status.configure(text="Scanning subnet for port 9000...", text_color=TEXT_MUTED)
        elif state == "progress":
            scan_status.configure(text=f"Scanning... {data}%", text_color=TEXT_MUTED)
        elif state == "done":
            scan_btn.configure(text="🔍 Auto Find", state="normal")
            if not data:
                scan_status.configure(text="No Quest found — see below", text_color=DANGER)
                tip_win = ctk.CTkToplevel(win)
                tip_win.title("Headset Not Found")
                tip_win.geometry("420x270")
                tip_win.configure(fg_color=SURFACE)
                tip_win.grab_set()
                ctk.CTkLabel(tip_win, text="Quest Not Found",
                             font=("Segoe UI", 14, "bold"),
                             text_color=TEXT_PRIMARY).pack(pady=(18, 4))
                ctk.CTkLabel(tip_win,
                             text="Is MAC Address Randomization turned ON on your Quest?",
                             font=("Segoe UI", 11), text_color=TEXT_MUTED,
                             justify="center").pack(pady=(0, 10))
                hint = ctk.CTkFrame(tip_win, fg_color=CARD, corner_radius=10)
                hint.pack(fill="x", padx=20, pady=(0, 10))
                ctk.CTkLabel(hint,
                    text="If YES - turn it OFF: Settings > Wi-Fi > tap your network > Advanced > MAC Address > Use Device MAC",
                    font=("Segoe UI", 11), text_color="#f59e0b",
                    justify="left").pack(padx=16, pady=10)
                ctk.CTkLabel(tip_win,
                             text="With randomization ON the MAC won't match Meta's vendor prefix so auto-detection fails.",
                             font=("Segoe UI", 10), text_color=TEXT_MUTED,
                             justify="center").pack(pady=(0, 10))
                ctk.CTkButton(tip_win, text="Got it", height=34,
                              font=("Segoe UI", 12, "bold"),
                              fg_color=ACCENT, hover_color="#1d4ed8",
                              text_color="#fff", corner_radius=8,
                              command=tip_win.destroy).pack(padx=20, fill="x", pady=(0, 16))
            elif len(data) == 1:
                ip, mac = data[0]
                _ip.delete(0, "end"); _ip.insert(0, ip)
                scan_status.configure(
                    text=f"✓ Quest found: {ip}  ({mac}) — click Apply",
                    text_color=SUCCESS)
            else:
                found_hosts.clear(); found_hosts.extend(data)
                pick_win = ctk.CTkToplevel(win)
                pick_win.title("Multiple Quest headsets found")
                pick_win.geometry("340x220")
                pick_win.configure(fg_color=SURFACE)
                pick_win.grab_set()
                ctk.CTkLabel(pick_win, text="Select your headset:",
                             font=("Segoe UI", 12, "bold"), text_color=TEXT_PRIMARY).pack(pady=(14,8))
                for ip, mac in data:
                    def _pick(i=ip, m=mac):
                        _ip.delete(0, "end"); _ip.insert(0, i)
                        scan_status.configure(
                            text=f"✓ Selected: {i} ({m}) — click Apply",
                            text_color=SUCCESS)
                        pick_win.destroy()
                    ctk.CTkButton(pick_win, text=f"{ip}  •  {mac}", height=32,
                                  font=("Segoe UI", 11), fg_color=BORDER,
                                  hover_color="#4b5563", text_color=TEXT_PRIMARY,
                                  command=_pick).pack(fill="x", padx=20, pady=3)

    scan_btn = ctk.CTkButton(scan_row, text="🔍 Auto Find", width=100, height=26,
                              font=("Segoe UI", 10, "bold"),
                              fg_color=BORDER, hover_color="#4b5563",
                              text_color=TEXT_PRIMARY, corner_radius=6,
                              command=lambda: scan_for_headset(_on_scan))
    scan_btn.pack(side="right")

    # ── Update ──
    upd = ctk.CTkFrame(win, fg_color=CARD, corner_radius=10)
    upd.pack(fill="x", padx=20, pady=(0, 10))
    ctk.CTkLabel(upd, text="APP UPDATE", font=("Segoe UI", 9, "bold"),
                 text_color=TEXT_MUTED).pack(anchor="w", padx=14, pady=(10, 4))
    upd_row = ctk.CTkFrame(upd, fg_color="transparent")
    upd_row.pack(fill="x", padx=14, pady=(0, 12))
    upd_status = ctk.CTkLabel(upd_row, text=f"v{APP_VERSION}",
                               font=("Consolas", 10), text_color=TEXT_MUTED, anchor="w")
    upd_status.pack(side="left", expand=True, fill="x")

    def _check_update():
        upd_btn.configure(text="Checking...", state="disabled")
        def _do():
            latest = check_for_update(silent=True)
            if latest:
                app.after(0, lambda: upd_status.configure(
                    text=f"Update available: v{APP_VERSION} → v{latest}", text_color=ACCENT))
                app.after(0, lambda: upd_btn.configure(
                    text=f"Install v{latest}", state="normal",
                    fg_color="#166534", hover_color="#14532d",
                    command=lambda: threading.Thread(
                        target=do_update, args=(latest,), daemon=True).start()))
            else:
                app.after(0, lambda: upd_status.configure(
                    text=f"✓ Up to date (v{APP_VERSION})", text_color=SUCCESS))
                app.after(0, lambda: upd_btn.configure(
                    text="Check for Updates", state="normal",
                    fg_color=ACCENT, hover_color="#1d4ed8",
                    command=_check_update))
        threading.Thread(target=_do, daemon=True).start()

    upd_btn = ctk.CTkButton(upd_row, text="Check for Updates", width=150, height=28,
                             font=("Segoe UI", 11, "bold"),
                             fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=8,
                             command=_check_update)
    upd_btn.pack(side="right")

    # ── Close ──
    ctk.CTkButton(win, text="Close", height=36,
                  font=("Segoe UI", 12, "bold"),
                  fg_color=BORDER, hover_color="#4b5563",
                  text_color=TEXT_PRIMARY, corner_radius=8,
                  command=win.destroy).pack(fill="x", padx=20, pady=(4, 18))

# ── Header ──
header = ctk.CTkFrame(app, fg_color="#0d1117", corner_radius=0, height=56)
header.pack(fill="x")
header.pack_propagate(False)

ctk.CTkLabel(header, text="●", font=("Segoe UI", 18), text_color=ACCENT).place(x=20, rely=0.5, anchor="w")
ctk.CTkLabel(header, text="OSC Banner", font=("Segoe UI", 15, "bold"), text_color=TEXT_PRIMARY).place(x=42, rely=0.5, anchor="w")

# Start / Stop in header
start_btn = ctk.CTkButton(
    header, text="▶  Start", font=("Segoe UI", 11, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=8, height=30, width=90,
    command=start_loop
)
start_btn.place(relx=0.5, x=-52, rely=0.5, anchor="center")

stop_btn = ctk.CTkButton(
    header, text="■  Stop", font=("Segoe UI", 11, "bold"),
    fg_color="#7f1d1d", hover_color="#991b1b", corner_radius=8, height=30, width=90,
    state="disabled", command=stop_loop
)
stop_btn.place(relx=0.5, x=52, rely=0.5, anchor="center")

# ⚙ Settings gear button
settings_btn = ctk.CTkButton(
    header, text="⚙", font=("Segoe UI", 16), width=36, height=36,
    fg_color="transparent", hover_color="#1f2937",
    text_color=TEXT_MUTED, corner_radius=8,
    command=open_settings
)
settings_btn.place(relx=1.0, x=-52, rely=0.5, anchor="center")

# (status pill moved below Now Sending card)

# ── Body ──
body = ctk.CTkFrame(app, fg_color=SURFACE)
body.pack(fill="both", expand=True, padx=20, pady=14)

# ── Now Sending ──
now_card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=58)
now_card.pack(fill="x", pady=(0, 4))
now_card.pack_propagate(False)
ctk.CTkLabel(now_card, text="NOW SENDING", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).place(x=14, y=9)
now_label = ctk.CTkLabel(now_card, text="—", font=("Segoe UI", 13, "bold"), text_color=ACCENT, anchor="w")
now_label.place(x=14, y=29)

# ── Status bar ──
status_frame = ctk.CTkFrame(body, fg_color="#1f2937", corner_radius=8, height=28)
status_frame.pack(fill="x", pady=(0, 8))
status_frame.pack_propagate(False)

status_dot = ctk.CTkLabel(status_frame, text="●", font=("Segoe UI", 11), text_color=DANGER)
status_dot.place(x=14, rely=0.5, anchor="w")
status_text = ctk.CTkLabel(status_frame, text="Stopped", font=("Segoe UI", 11, "bold"), text_color=DANGER)
status_text.place(x=30, rely=0.5, anchor="w")

# ══════════════════════════════════════════════════════
# SOURCE SELECTOR — slide animation between Spotify/Discord
# ══════════════════════════════════════════════════════

DISCORD_BLUE  = "#5865f2"
DISCORD_DARK  = "#0d0f1f"
DISCORD_BORDER= "#1e2040"

# Arrow label between source cards
source_arrow_label = ctk.CTkLabel(
    body, text="▼  Switch Source  ▼",
    font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED
)
source_arrow_label.pack(pady=(0, 4))

# Container that holds both cards side by side — we slide it
slide_container_outer = ctk.CTkFrame(body, fg_color="transparent")
slide_container_outer.pack(fill="x", pady=(0, 8))

# Inner frame — 3 panels wide (spotify / discord / style)
slide_inner = ctk.CTkFrame(slide_container_outer, fg_color="transparent")
slide_inner.place(x=0, y=0, relwidth=3.0, relheight=1.0)

# Build all cards inside slide_inner side by side
_slide_x     = [0]
_slide_target= [0]
_slide_animating = [False]
_CARD_WIDTH  = 560

def _animate_slide():
    cur = _slide_x[0]
    tgt = _slide_target[0]
    if abs(cur - tgt) < 2:
        _slide_x[0] = tgt
        slide_inner.place_configure(x=tgt)
        _slide_animating[0] = False
        return
    step = (tgt - cur) * 0.25
    if abs(step) < 1:
        step = 1 if tgt > cur else -1
    new_x = cur + step
    _slide_x[0] = new_x
    slide_inner.place_configure(x=int(new_x))
    app.after(16, _animate_slide)

def switch_to_source(source):
    global active_source
    active_source = source
    save_settings()
    w = slide_container_outer.winfo_width() or 520
    if source == "spotify":
        target = 0
    elif source == "discord":
        target = -w
    else:  # style
        target = -w * 2
    _slide_target[0] = target
    if not _slide_animating[0]:
        _slide_animating[0] = True
        _animate_slide()
    tab_spotify_btn.configure(fg_color=ACCENT       if source=="spotify" else BORDER,
                               text_color="#fff"     if source=="spotify" else TEXT_MUTED)
    tab_discord_btn.configure(fg_color=DISCORD_BLUE if source=="discord" else BORDER,
                               text_color="#fff"     if source=="discord" else TEXT_MUTED)
    tab_style_btn.configure(  fg_color="#7c3aed"    if source=="style"   else BORDER,
                               text_color="#fff"     if source=="style"   else TEXT_MUTED)

# ── Tab switcher buttons ──
tab_row = ctk.CTkFrame(body, fg_color="transparent")
tab_row.pack(fill="x", pady=(0, 4))

tab_spotify_btn = ctk.CTkButton(
    tab_row, text="♫  Spotify", font=("Segoe UI", 11, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8",
    text_color="#fff", corner_radius=8, height=28,
    command=lambda: switch_to_source("spotify")
)
tab_spotify_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

tab_discord_btn = ctk.CTkButton(
    tab_row, text="⬡  Discord", font=("Segoe UI", 11, "bold"),
    fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_MUTED, corner_radius=8, height=28,
    command=lambda: switch_to_source("discord")
)
tab_discord_btn.pack(side="left", expand=True, fill="x", padx=(4, 4))

tab_style_btn = ctk.CTkButton(
    tab_row, text="✦  Style", font=("Segoe UI", 11, "bold"),
    fg_color=BORDER, hover_color="#5b21b6",
    text_color=TEXT_MUTED, corner_radius=8, height=28,
    command=lambda: switch_to_source("style")
)
tab_style_btn.pack(side="left", expand=True, fill="x")

# Height holder so container has a size
slide_container_outer.configure(height=240)
slide_container_outer.pack_propagate(False)

# ── Spotify panel (1st third of slide_inner) ──
spotify_panel = ctk.CTkFrame(slide_inner, fg_color="#0d1f12", corner_radius=12,
                              border_width=1, border_color="#1c3828")
spotify_panel.place(relx=0, rely=0, relwidth=0.333, relheight=1.0)

# ── Discord panel (2nd third of slide_inner) ──
discord_panel = ctk.CTkFrame(slide_inner, fg_color=DISCORD_DARK, corner_radius=12,
                              border_width=1, border_color=DISCORD_BORDER)
discord_panel.place(relx=0.333, rely=0, relwidth=0.333, relheight=1.0)

# ── Style panel (3rd third of slide_inner) ──
style_panel = ctk.CTkFrame(slide_inner, fg_color="#1a0e2e", corner_radius=12,
                            border_width=1, border_color="#3b1f6e")
style_panel.place(relx=0.666, rely=0, relwidth=0.333, relheight=1.0)

# ─────────────────────────────────────────
# Spotify card contents (inside spotify_panel)
# ─────────────────────────────────────────
sp_header = ctk.CTkFrame(spotify_panel, fg_color="transparent")
sp_header.place(x=14, y=10)
ctk.CTkLabel(sp_header, text="♫", font=("Segoe UI", 15), text_color=SPOTIFY_GREEN).pack(side="left", padx=(0, 5))
ctk.CTkLabel(sp_header, text="SPOTIFY", font=("Segoe UI", 9, "bold"), text_color=SPOTIFY_GREEN).pack(side="left")

spotify_login_btn = ctk.CTkButton(
    spotify_panel, text="Login with Spotify", width=152, height=28,
    font=("Segoe UI", 11, "bold"),
    fg_color=SPOTIFY_GREEN, hover_color="#17a349", text_color="#000000",
    corner_radius=20, command=do_spotify_login
)
spotify_login_btn.place(relx=1.0, x=-14, y=10)

spotify_status_label = ctk.CTkLabel(spotify_panel,
    text="Not connected — click Login to authorize",
    font=("Segoe UI", 9), text_color=TEXT_MUTED)
spotify_status_label.place(x=14, y=32)

spotify_track_label = ctk.CTkLabel(spotify_panel, text="—",
    font=("Segoe UI", 11, "bold"), text_color=TEXT_MUTED,
    anchor="w", wraplength=260)
spotify_track_label.place(x=14, y=50)

sp_bottom = ctk.CTkFrame(spotify_panel, fg_color="transparent")
sp_bottom.place(x=14, y=88, relwidth=0.97)

manual_artist_entry = ctk.CTkEntry(
    sp_bottom, placeholder_text="Artist",
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=90, height=24, corner_radius=6
)
manual_artist_entry.pack(side="left", padx=(0, 4))

manual_song_entry = ctk.CTkEntry(
    sp_bottom, placeholder_text="Song",
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=90, height=24, corner_radius=6
)
manual_song_entry.pack(side="left", padx=(0, 4))

ctk.CTkButton(
    sp_bottom, text="Set", width=50, height=24,
    font=("Segoe UI", 10), fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_PRIMARY, corner_radius=6,
    command=use_manual_track
).pack(side="left", padx=(0, 4))

spotify_banner_btn = ctk.CTkButton(
    sp_bottom, text="+ Banner", width=80, height=24,
    font=("Segoe UI", 10, "bold"),
    fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_PRIMARY, corner_radius=6,
    command=toggle_spotify_banner
)
spotify_banner_btn.pack(side="left")

# ─────────────────────────────────────────
# Discord card contents (inside discord_panel)
# ─────────────────────────────────────────
dc_header = ctk.CTkFrame(discord_panel, fg_color="transparent")
dc_header.place(x=14, y=10)
ctk.CTkLabel(dc_header, text="⬡", font=("Segoe UI", 15), text_color=DISCORD_BLUE).pack(side="left", padx=(0, 5))
ctk.CTkLabel(dc_header, text="DISCORD", font=("Segoe UI", 9, "bold"), text_color=DISCORD_BLUE).pack(side="left")

discord_login_btn = ctk.CTkButton(
    discord_panel, text="Login with Discord", width=152, height=28,
    font=("Segoe UI", 11, "bold"),
    fg_color=DISCORD_BLUE, hover_color="#4338ca", text_color="#fff",
    corner_radius=20, command=do_discord_login
)
discord_login_btn.place(relx=1.0, x=-14, y=10)

discord_status_label = ctk.CTkLabel(discord_panel,
    text="Not connected — click Login to authorize",
    font=("Segoe UI", 9), text_color=TEXT_MUTED)
discord_status_label.place(x=14, y=32)

discord_info_label = ctk.CTkLabel(discord_panel, text="—",
    font=("Segoe UI", 11, "bold"), text_color=TEXT_MUTED,
    anchor="w", wraplength=260)
discord_info_label.place(x=14, y=50)

dc_bottom = ctk.CTkFrame(discord_panel, fg_color="transparent")
dc_bottom.place(x=14, y=88, relwidth=0.97)

discord_banner_btn = ctk.CTkButton(
    dc_bottom, text="+ Add to Banner", width=130, height=24,
    font=("Segoe UI", 10, "bold"),
    fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_PRIMARY, corner_radius=6,
    command=toggle_discord_banner
)
discord_banner_btn.pack(side="left")

# ─────────────────────────────────────────
# Style panel — self-contained caption composer
# All state is LOCAL to this composer, not global
# ─────────────────────────────────────────
sty_header = ctk.CTkFrame(style_panel, fg_color="transparent")
sty_header.place(x=14, y=6)
ctk.CTkLabel(sty_header, text="✦", font=("Segoe UI", 13), text_color="#a78bfa").pack(side="left", padx=(0,5))
ctk.CTkLabel(sty_header, text="STYLE  COMPOSER", font=("Segoe UI", 9, "bold"), text_color="#a78bfa").pack(side="left")

# Local composer state
_c_border_char  = ["~"]
_c_border_on    = [True]
_c_padding      = [2]
_c_time_format  = ["none"]
_c_prefix       = [""]
_c_suffix       = [""]
_c_template     = ["{text}"]

def _c_snapshot():
    return {
        "border_char":  _c_border_char[0],
        "border_on":    _c_border_on[0],
        "padding":      _c_padding[0],
        "time_format":  _c_time_format[0],
        "prefix":       _c_prefix[0],
        "suffix":       _c_suffix[0],
        "template":     _c_template[0],
    }

# Preview label
style_preview = ctk.CTkLabel(style_panel, text="",
    font=("Consolas", 8), text_color="#c4b5fd", anchor="w",
    wraplength=260, justify="left")
style_preview.place(x=14, y=26)

def refresh_style_preview(*_):
    try:
        raw = style_caption_entry.get().strip()
    except:
        raw = ""
    sample = raw or "Hello VRChat"
    result = format_caption(sample, _c_snapshot())
    style_preview.configure(text=result.replace("\n", "  ")[:100])

# ── Row 1: Border char buttons ──
border_row = ctk.CTkFrame(style_panel, fg_color="transparent")
border_row.place(x=14, y=88, relwidth=0.93)

BORDER_OPTIONS = ["~", "#", "*", "=", "-", "none"]

def _set_border(ch):
    if ch == "none":
        _c_border_on[0] = False
    else:
        _c_border_on[0]   = True
        _c_border_char[0] = ch
    refresh_style_preview()
    for b, opt in _border_btns:
        active = (opt == ch and ch != "none") or (opt == "none" and not _c_border_on[0])
        b.configure(fg_color="#7c3aed" if active else BORDER,
                    text_color="#fff"  if active else TEXT_MUTED)

_border_btns = []
for opt in BORDER_OPTIONS:
    label = "off" if opt == "none" else opt*2
    btn = ctk.CTkButton(border_row, text=label, width=38, height=22,
                        font=("Consolas", 10, "bold"),
                        fg_color=BORDER, hover_color="#5b21b6",
                        text_color=TEXT_MUTED, corner_radius=5,
                        command=lambda o=opt: _set_border(o))
    btn.pack(side="left", padx=2)
    _border_btns.append((btn, opt))

# Custom border char entry
custom_border_entry = ctk.CTkEntry(border_row, width=38, height=22,
    font=("Consolas", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=5,
    placeholder_text="?", placeholder_text_color=TEXT_MUTED)
custom_border_entry.pack(side="left", padx=2)

def _apply_custom_border(e=None):
    ch = custom_border_entry.get().strip()
    if ch:
        _set_border(ch[:1])
custom_border_entry.bind("<Return>", _apply_custom_border)
custom_border_entry.bind("<FocusOut>", _apply_custom_border)

# ── Row 2: Padding + time format ──
mid_row = ctk.CTkFrame(style_panel, fg_color="transparent")
mid_row.place(x=14, y=118, relwidth=0.93)

ctk.CTkLabel(mid_row, text="pad", font=("Segoe UI", 9), text_color=TEXT_MUTED).pack(side="left")
pad_var = ctk.StringVar(value=str(_c_padding[0]))
pad_spin = ctk.CTkEntry(mid_row, width=36, height=22, textvariable=pad_var,
    font=("Consolas", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=5)
pad_spin.pack(side="left", padx=(4, 12))

def _pad_changed(e=None):
    try:
        _c_padding[0] = max(0, min(10, int(pad_var.get())))
        refresh_style_preview()
    except: pass
pad_spin.bind("<Return>", _pad_changed)
pad_spin.bind("<FocusOut>", _pad_changed)

ctk.CTkLabel(mid_row, text="time", font=("Segoe UI", 9), text_color=TEXT_MUTED).pack(side="left")
TIME_OPTS = [("off","none"),("12h","12hr"),("24h","24hr"),("D+T","datetime")]
_time_btns = []
for label, val in TIME_OPTS:
    tb = ctk.CTkButton(mid_row, text=label, width=36, height=22,
                       font=("Segoe UI", 9, "bold"),
                       fg_color="#7c3aed" if _c_time_format[0]==val else BORDER,
                       hover_color="#5b21b6",
                       text_color="#fff" if _c_time_format[0]==val else TEXT_MUTED,
                       corner_radius=5,
                       command=lambda v=val: _set_time(v))
    tb.pack(side="left", padx=2)
    _time_btns.append((tb, val))

def _set_time(val):
    _c_time_format[0] = val
    refresh_style_preview()
    for b, v in _time_btns:
        b.configure(fg_color="#7c3aed" if v==val else BORDER,
                    text_color="#fff"  if v==val else TEXT_MUTED)

# ── Row 3: Prefix / Suffix ──
fix_row = ctk.CTkFrame(style_panel, fg_color="transparent")
fix_row.place(x=14, y=146, relwidth=0.93)

ctk.CTkLabel(fix_row, text="pre", font=("Segoe UI", 9), text_color=TEXT_MUTED).pack(side="left")
prefix_entry = ctk.CTkEntry(fix_row, width=62, height=22,
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=5,
    placeholder_text="🎵", placeholder_text_color=TEXT_MUTED)

prefix_entry.pack(side="left", padx=(4,10))

ctk.CTkLabel(fix_row, text="suf", font=("Segoe UI", 9), text_color=TEXT_MUTED).pack(side="left")
suffix_entry = ctk.CTkEntry(fix_row, width=62, height=22,
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=5,
    placeholder_text="✨", placeholder_text_color=TEXT_MUTED)

suffix_entry.pack(side="left", padx=(4,0))

def _fix_changed(e=None):
    _c_prefix[0] = prefix_entry.get()
    _c_suffix[0] = suffix_entry.get()
    refresh_style_preview()
prefix_entry.bind("<KeyRelease>", _fix_changed)
suffix_entry.bind("<KeyRelease>", _fix_changed)

# ── Row 4: Template ──
tpl_row = ctk.CTkFrame(style_panel, fg_color="transparent")
tpl_row.place(x=14, y=172, relwidth=0.93)

ctk.CTkLabel(tpl_row, text="tpl", font=("Segoe UI", 9), text_color=TEXT_MUTED).pack(side="left")
tpl_entry = ctk.CTkEntry(tpl_row, height=22,
    font=("Consolas", 9), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=5,
    placeholder_text="{text} | {time}", placeholder_text_color=TEXT_MUTED)
tpl_entry.insert(0, _c_template[0])
tpl_entry.pack(side="left", expand=True, fill="x", padx=(4,0))

def _tpl_changed(e=None):
    t = tpl_entry.get().strip()
    _c_template[0] = t if t else "{text}"
    refresh_style_preview()
tpl_entry.bind("<KeyRelease>", _tpl_changed)

# ── Row 5: Add to Captions ──
add_row = ctk.CTkFrame(style_panel, fg_color="transparent")
add_row.place(x=14, y=192, relwidth=0.93)

style_caption_entry = ctk.CTkEntry(add_row, height=26,
    font=("Segoe UI", 11), fg_color=SURFACE, border_color="#3b1f6e",
    border_width=1, text_color=TEXT_PRIMARY, corner_radius=6,
    placeholder_text="type caption…", placeholder_text_color=TEXT_MUTED)
style_caption_entry.pack(side="left", expand=True, fill="x", padx=(0, 6))

def _style_add_caption(e=None):
    raw = style_caption_entry.get().strip()
    if not raw:
        return
    captions.append({"text": raw, "style": _c_snapshot()})
    style_caption_entry.delete(0, "end")
    try:
        refresh_list()
        save_json()
        list_scroll.after(50, lambda: list_scroll._parent_canvas.yview_moveto(1.0))
    except: pass

style_caption_entry.bind("<Return>", _style_add_caption)

ctk.CTkButton(add_row, text="+ Add", width=60, height=26,
    font=("Segoe UI", 10, "bold"),
    fg_color="#7c3aed", hover_color="#5b21b6",
    text_color="#fff", corner_radius=6,
    command=_style_add_caption).pack(side="left")

# Init style composer button states
_set_border(_c_border_char[0] if _c_border_on[0] else "none")
_set_time(_c_time_format[0])
refresh_style_preview()

# Set initial tab position based on saved preference
app.after(200, lambda: switch_to_source(active_source))

# ── IP Config ──
ip_card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=60)
ip_card.pack(fill="x", pady=(0, 8))
ip_card.pack_propagate(False)
ctk.CTkLabel(ip_card, text="TARGET", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).place(x=14, y=8)

ip_row = ctk.CTkFrame(ip_card, fg_color="transparent")
ip_row.place(x=14, y=28, relwidth=0.98)

ip_entry = ctk.CTkEntry(
    ip_row, placeholder_text="IP Address",
    font=("Consolas", 12), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=160, height=26, corner_radius=6
)
ip_entry.insert(0, VRCHAT_IP)
ip_entry.pack(side="left", padx=(0, 6))

port_entry = ctk.CTkEntry(
    ip_row, placeholder_text="Port",
    font=("Consolas", 12), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=72, height=26, corner_radius=6
)
port_entry.insert(0, str(VRCHAT_PORT))
port_entry.pack(side="left", padx=(0, 8))

apply_btn = ctk.CTkButton(
    ip_row, text="Apply", width=62, height=26,
    font=("Segoe UI", 11, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=6,
    command=apply_ip
)
apply_btn.pack(side="left")

ip_status = ctk.CTkLabel(ip_row, text="", font=("Segoe UI", 10),
                         text_color=SUCCESS, width=100, anchor="w")
ip_status.pack(side="left", padx=(8, 0))

# ── Caption Input ──
input_frame = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=78)
input_frame.pack(fill="x", pady=(0, 8))
input_frame.pack_propagate(False)

entry = ctk.CTkEntry(
    input_frame,
    placeholder_text="New caption… use {time} for clock",
    font=("Segoe UI", 12),
    fg_color="transparent", border_width=0,
    text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_MUTED
)
entry.place(x=12, y=10, relwidth=0.82)
entry.bind("<Return>", on_entry_return)

add_btn = ctk.CTkButton(
    input_frame, text="+ Add", width=76, height=32,
    font=("Segoe UI", 12, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=8,
    command=add_caption
)
add_btn.place(relx=1.0, x=-10, y=10, anchor="ne")

# Styled preview under the entry
entry_preview_lbl = ctk.CTkLabel(
    input_frame, text="", font=("Segoe UI", 9),
    text_color=TEXT_MUTED, anchor="w"
)
entry_preview_lbl.place(x=12, y=44, relwidth=0.95)

def _update_entry_preview(*_):
    try:
        entry_preview_lbl.winfo_exists()
    except NameError:
        return
    raw = entry.get().strip()
    entry_preview_lbl.configure(text=raw)  # plain — no global style

entry.bind("<KeyRelease>", _update_entry_preview)

# ── Caption List ──
list_header_row = ctk.CTkFrame(body, fg_color="transparent")
list_header_row.pack(fill="x", pady=(2, 4))
ctk.CTkLabel(list_header_row, text="CAPTIONS", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).pack(side="left")
count_label = ctk.CTkLabel(list_header_row, text="0 captions", font=("Segoe UI", 10), text_color=TEXT_MUTED)
count_label.pack(side="right")

list_scroll = ctk.CTkScrollableFrame(
    body, fg_color=SURFACE, scrollbar_button_color=BORDER,
    scrollbar_button_hover_color=ACCENT, corner_radius=10, height=150
)
list_scroll.pack(fill="both", expand=True, pady=(0, 8))
list_inner = list_scroll

# ── Delay ──
delay_card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=56)
delay_card.pack(fill="x", pady=(0, 10))
delay_card.pack_propagate(False)

delay_row = ctk.CTkFrame(delay_card, fg_color="transparent")
delay_row.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.94)
ctk.CTkLabel(delay_row, text="INTERVAL", font=("Segoe UI", 9, "bold"),
             text_color=TEXT_MUTED, width=64, anchor="w").pack(side="left")
delay_slider = ctk.CTkSlider(
    delay_row, from_=1, to=15,
    fg_color=BORDER, progress_color=ACCENT,
    button_color=TEXT_PRIMARY, button_hover_color=ACCENT,
    command=update_delay_label
)
delay_slider.set(5)
delay_slider.pack(side="left", expand=True, padx=10)
delay_val_label = ctk.CTkLabel(delay_row, text="5.0s", font=("Segoe UI", 13, "bold"),
                               text_color=TEXT_PRIMARY, width=44, anchor="e")
delay_val_label.pack(side="right")





# ── Footer ──
footer = ctk.CTkFrame(app, fg_color="#0d1117", corner_radius=0, height=30)
footer.pack(fill="x", side="bottom")
footer.pack_propagate(False)

footer_target = ctk.CTkLabel(footer, text=f"->  {VRCHAT_IP}:{VRCHAT_PORT}",
                              font=("Consolas", 10), text_color=TEXT_MUTED)
footer_target.place(x=16, rely=0.5, anchor="w")

ctk.CTkLabel(footer, text="made by adam77461",
             font=("Segoe UI", 9), text_color=BORDER).place(relx=0.5, rely=0.5, anchor="center")

ctk.CTkLabel(footer, text="OSC /chatbox/input",
             font=("Consolas", 10), text_color=BORDER).place(relx=1.0, x=-16, rely=0.5, anchor="e")

# ── Init ──
try:
    load_json(DEFAULT_FILE)
except:
    captions = [{"text": "sleeping zzz", "style": None}, {"text": "{time}", "style": None}, {"text": "miku miku beam", "style": None}]
    save_json()
    refresh_list()

# Restore saved Spotify session if available
if load_tokens() and spotify_refresh_token:
    spotify_enabled = True
    spotify_login_btn.configure(text="Connected!", fg_color="#166634")
    spotify_status_label.configure(text="Session restored", text_color=SUCCESS)
    start_spotify_poller()

# Restore saved Discord session if available
if discord_load_tokens() and discord_refresh_token:
    discord_enabled = True
    discord_login_btn.configure(text="Connected!", fg_color="#3730a3")
    discord_status_label.configure(text="Session restored", text_color="#818cf8")
    start_discord_poller()

# Auto-check for updates on launch
app.after(2000, auto_check_update)

app.mainloop()
