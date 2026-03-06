"""
VRChat OSC Banner — Android (Termux) Edition
by adam77461
Flask web UI served locally, opened in Android browser
"""

import json
import threading
import time
import hashlib
import secrets as _secrets
import urllib.parse
import urllib.request
import socket
import ipaddress
import subprocess
import os
import webbrowser
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, session
from pythonosc.udp_client import SimpleUDPClient

# ── Config ──
DEFAULT_FILE   = "captions.json"
TOKEN_FILE     = "spotify_token.json"
PORT           = 5000
SECRET_KEY     = _secrets.token_hex(16)

SPOTIFY_CLIENT_ID    = "690ecc75dfae468e9e8dc3a4697609fc"
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:5000/spotify/callback"
SPOTIFY_SCOPE        = "user-read-currently-playing user-read-playback-state"

SPOTIFY_SEND_DURATION  = 240   # 4 minutes
SPOTIFY_CHECK_INTERVAL = 30    # seconds

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ── State ──
state = {
    "running": False,
    "captions": [],
    "current_file": DEFAULT_FILE,
    "vrchat_ip": "",
    "vrchat_port": 9000,
    "delay": 5,
    "osc": None,

    # Spotify
    "spotify_token": None,
    "spotify_refresh": None,
    "spotify_expiry": 0,
    "spotify_enabled": False,
    "spotify_now_playing": "",
    "spotify_status": "Not connected",
    "spotify_in_banner": False,

    # Spotify banner engine
    "spotify_banner_running": False,
    "spotify_caption_text": "",

    # IP scan
    "scan_results": [],
    "scanning": False,
    "scan_progress": 0,

    # PKCE
    "_pkce_verifier": None,
}

osc_lock = threading.Lock()


# ═══════════════════════════════════════════════
#  OSC
# ═══════════════════════════════════════════════
def get_osc():
    if state["osc"] and state["vrchat_ip"]:
        return state["osc"]
    return None

def reconnect_osc(ip, port):
    with osc_lock:
        state["osc"] = SimpleUDPClient(ip, int(port))
        state["vrchat_ip"] = ip
        state["vrchat_port"] = int(port)

def format_caption(text, padding=3):
    width  = len(text) + padding * 2
    border = "~" * width
    middle = " " * padding + text + " " * padding
    return f"{border}\n{middle}\n{border}"

def send_osc(text):
    osc = get_osc()
    if osc:
        try:
            osc.send_message("/chatbox/input", [format_caption(text), True, False])
        except Exception as e:
            print(f"OSC error: {e}")


# ═══════════════════════════════════════════════
#  JSON persistence
# ═══════════════════════════════════════════════
def load_captions(path=None):
    path = path or state["current_file"]
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            state["captions"] = data.get("captions", [])
            state["current_file"] = path
    except:
        pass

def save_captions():
    with open(state["current_file"], "w", encoding="utf-8") as f:
        json.dump({"captions": state["captions"]}, f, indent=4, ensure_ascii=False)


# ═══════════════════════════════════════════════
#  Network — VRChat headset auto-detection
# ═══════════════════════════════════════════════
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "192.168.1.1"

def get_subnet(local_ip):
    parts = local_ip.rsplit(".", 1)
    return parts[0]

def ping_host(ip):
    """Ping a host, return True if alive."""
    try:
        result = subprocess.run(
            ["ping", "-c", "1", "-W", "1", str(ip)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2
        )
        return result.returncode == 0
    except:
        return False

def check_osc_port(ip, port=9000):
    """Try sending a UDP packet to OSC port — if no immediate error, likely open."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        sock.sendto(b"\x00", (str(ip), port))
        sock.close()
        return True
    except:
        return False

def get_hostname(ip):
    try:
        return socket.gethostbyaddr(str(ip))[0]
    except:
        return ""

def scan_network():
    """Scan local subnet for hosts with OSC port 9000 open (likely VRChat)."""
    state["scanning"] = True
    state["scan_results"] = []
    state["scan_progress"] = 0

    local_ip = get_local_ip()
    subnet = get_subnet(local_ip)
    hosts = [f"{subnet}.{i}" for i in range(1, 255)]
    found = []
    total = len(hosts)

    def check(ip):
        if ping_host(ip):
            hostname = get_hostname(ip)
            if check_osc_port(ip):
                found.append({
                    "ip": ip,
                    "hostname": hostname,
                    "osc": True,
                    "label": f"{hostname} ({ip})" if hostname else ip
                })
            else:
                found.append({
                    "ip": ip,
                    "hostname": hostname,
                    "osc": False,
                    "label": f"{hostname} ({ip})" if hostname else ip
                })

    threads = []
    batch = 20
    for i in range(0, total, batch):
        chunk = hosts[i:i+batch]
        batch_threads = [threading.Thread(target=check, args=(ip,), daemon=True) for ip in chunk]
        for t in batch_threads:
            t.start()
        for t in batch_threads:
            t.join(timeout=3)
        threads.extend(batch_threads)
        state["scan_progress"] = min(100, int((i + batch) / total * 100))

    # Sort: OSC hosts first
    found.sort(key=lambda x: (0 if x["osc"] else 1, x["ip"]))
    state["scan_results"] = found
    state["scanning"] = False
    state["scan_progress"] = 100
    print(f"Scan complete — found {len(found)} hosts, {sum(1 for h in found if h['osc'])} with OSC port open")


# ═══════════════════════════════════════════════
#  Spotify PKCE Auth
# ═══════════════════════════════════════════════
def _generate_pkce():
    verifier  = _secrets.token_urlsafe(64)
    import base64
    digest    = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge

def save_tokens():
    with open(TOKEN_FILE, "w") as f:
        json.dump({
            "access_token":  state["spotify_token"],
            "refresh_token": state["spotify_refresh"],
            "expiry":        state["spotify_expiry"]
        }, f)

def load_tokens():
    try:
        with open(TOKEN_FILE, "r") as f:
            d = json.load(f)
        state["spotify_token"]   = d.get("access_token")
        state["spotify_refresh"] = d.get("refresh_token")
        state["spotify_expiry"]  = d.get("expiry", 0)
        return True
    except:
        return False

def exchange_code(code, verifier):
    data = urllib.parse.urlencode({
        "grant_type":    "authorization_code",
        "code":          code,
        "redirect_uri":  SPOTIFY_REDIRECT_URI,
        "client_id":     SPOTIFY_CLIENT_ID,
        "code_verifier": verifier,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    with urllib.request.urlopen(req) as resp:
        r = json.loads(resp.read())
    state["spotify_token"]   = r["access_token"]
    state["spotify_refresh"] = r.get("refresh_token")
    state["spotify_expiry"]  = time.time() + r.get("expires_in", 3600) - 60
    save_tokens()

def refresh_token():
    if not state["spotify_refresh"]:
        return False
    data = urllib.parse.urlencode({
        "grant_type":    "refresh_token",
        "refresh_token": state["spotify_refresh"],
        "client_id":     SPOTIFY_CLIENT_ID,
    }).encode()
    req = urllib.request.Request(
        "https://accounts.spotify.com/api/token", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            r = json.loads(resp.read())
        state["spotify_token"]  = r["access_token"]
        state["spotify_expiry"] = time.time() + r.get("expires_in", 3600) - 60
        if "refresh_token" in r:
            state["spotify_refresh"] = r["refresh_token"]
        save_tokens()
        return True
    except:
        return False

def ensure_token():
    if time.time() >= state["spotify_expiry"]:
        return refresh_token()
    return state["spotify_token"] is not None

def get_now_playing():
    if not ensure_token():
        state["spotify_status"] = "Token expired — re-login"
        return None
    req = urllib.request.Request(
        "https://api.spotify.com/v1/me/player/currently-playing",
        headers={"Authorization": f"Bearer {state['spotify_token']}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            if resp.status == 204:
                state["spotify_status"] = "Connected — nothing playing"
                return None
            data = json.loads(resp.read())
            if data and data.get("is_playing") and data.get("item"):
                item    = data["item"]
                artists = ", ".join(a["name"] for a in item["artists"])
                track   = item["name"]
                state["spotify_status"] = "Playing"
                return f"Now Playing: {artists} - {track}"
            elif data and not data.get("is_playing"):
                state["spotify_status"] = "Paused"
            return None
    except urllib.error.HTTPError as e:
        if e.code == 403:
            state["spotify_status"] = "403 — Spotify Premium required"
        elif e.code == 401:
            state["spotify_status"] = "401 — Re-login required"
        else:
            state["spotify_status"] = f"HTTP {e.code} error"
        return None
    except Exception as e:
        state["spotify_status"] = "Network error"
        return None


# ═══════════════════════════════════════════════
#  Caption loop
# ═══════════════════════════════════════════════
caption_index = [0]

def caption_loop():
    while state["running"]:
        captions = list(state["captions"])
        if not captions:
            time.sleep(0.5)
            continue
        idx     = caption_index[0] % len(captions)
        caption = captions[idx]
        caption_index[0] = idx + 1

        if caption == "{time}":
            text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            text = caption

        send_osc(text)
        time.sleep(state["delay"])

def start_loop():
    if not state["running"]:
        state["running"] = True
        caption_index[0] = 0
        threading.Thread(target=caption_loop, daemon=True).start()

def stop_loop():
    state["running"] = False


# ═══════════════════════════════════════════════
#  Spotify poller + banner engine
# ═══════════════════════════════════════════════
spotify_poll_running = [False]

def start_spotify_poller():
    if not spotify_poll_running[0]:
        spotify_poll_running[0] = True
        threading.Thread(target=_spotify_poll_loop, daemon=True).start()

def _spotify_poll_loop():
    while spotify_poll_running[0]:
        track = get_now_playing()
        new   = track or ""
        if new != state["spotify_now_playing"]:
            state["spotify_now_playing"] = new
        time.sleep(10)

def start_spotify_banner():
    if not state["spotify_banner_running"]:
        state["spotify_banner_running"] = True
        threading.Thread(target=_spotify_banner_loop, daemon=True).start()

def _spotify_banner_loop():
    while state["spotify_in_banner"] and state["spotify_banner_running"]:
        current = state["spotify_now_playing"]

        if not current:
            state["spotify_status"] = "Waiting for a song..."
            time.sleep(SPOTIFY_CHECK_INTERVAL)
            continue

        if current != state["spotify_caption_text"]:
            state["spotify_caption_text"] = current
            state["spotify_status"] = f"Sending to VRChat"

        send_osc(state["spotify_caption_text"])

        elapsed = 0
        while elapsed < SPOTIFY_SEND_DURATION and state["spotify_in_banner"]:
            time.sleep(SPOTIFY_CHECK_INTERVAL)
            elapsed += SPOTIFY_CHECK_INTERVAL

            latest = state["spotify_now_playing"]
            if not latest:
                state["spotify_caption_text"] = ""
                state["spotify_status"] = "Song ended — removed"
                break

            if latest != state["spotify_caption_text"]:
                state["spotify_status"] = "Song changed — switching"
                break

            remaining = SPOTIFY_SEND_DURATION - elapsed
            m, s = divmod(int(remaining), 60)
            state["spotify_status"] = f"Sending — {m}m {s:02d}s left"
            send_osc(state["spotify_caption_text"])
        else:
            if state["spotify_now_playing"] == state["spotify_caption_text"]:
                state["spotify_status"] = "Renewing — still playing"
            else:
                state["spotify_caption_text"] = ""
                state["spotify_status"] = "Expired — song changed"

    state["spotify_banner_running"] = False


# ═══════════════════════════════════════════════
#  Flask Routes
# ═══════════════════════════════════════════════

@app.route("/")
def index():
    load_captions()
    return render_template("index.html",
        captions     = state["captions"],
        running      = state["running"],
        vrchat_ip    = state["vrchat_ip"],
        vrchat_port  = state["vrchat_port"],
        delay        = state["delay"],
        spotify_status      = state["spotify_status"],
        spotify_enabled     = state["spotify_enabled"],
        spotify_now_playing = state["spotify_now_playing"],
        spotify_in_banner   = state["spotify_in_banner"],
        local_ip     = get_local_ip(),
    )

# ── Captions ──
@app.route("/captions/add", methods=["POST"])
def add_caption():
    text = request.json.get("text", "").strip()
    if text:
        state["captions"].append(text)
        save_captions()
    return jsonify(captions=state["captions"])

@app.route("/captions/delete/<int:idx>", methods=["POST"])
def delete_caption(idx):
    if 0 <= idx < len(state["captions"]):
        state["captions"].pop(idx)
        save_captions()
    return jsonify(captions=state["captions"])

@app.route("/captions/clear", methods=["POST"])
def clear_captions():
    state["captions"].clear()
    save_captions()
    return jsonify(captions=state["captions"])

# ── Control ──
@app.route("/control/start", methods=["POST"])
def control_start():
    if not state["vrchat_ip"]:
        return jsonify(ok=False, error="No VRChat IP set")
    start_loop()
    return jsonify(ok=True, running=True)

@app.route("/control/stop", methods=["POST"])
def control_stop():
    stop_loop()
    return jsonify(ok=True, running=False)

@app.route("/control/delay", methods=["POST"])
def set_delay():
    val = float(request.json.get("delay", 5))
    state["delay"] = max(1, min(15, val))
    return jsonify(delay=state["delay"])

# ── Target IP ──
@app.route("/target/set", methods=["POST"])
def set_target():
    ip   = request.json.get("ip", "").strip()
    port = int(request.json.get("port", 9000))
    if not ip:
        return jsonify(ok=False, error="IP required")
    try:
        reconnect_osc(ip, port)
        return jsonify(ok=True, ip=ip, port=port)
    except Exception as e:
        return jsonify(ok=False, error=str(e))

# ── Network scan ──
@app.route("/scan/start", methods=["POST"])
def scan_start():
    if not state["scanning"]:
        threading.Thread(target=scan_network, daemon=True).start()
    return jsonify(ok=True)

@app.route("/scan/status")
def scan_status():
    return jsonify(
        scanning  = state["scanning"],
        progress  = state["scan_progress"],
        results   = state["scan_results"],
    )

# ── Spotify ──
@app.route("/spotify/login")
def spotify_login():
    verifier, challenge = _generate_pkce()
    state["_pkce_verifier"] = verifier
    params = urllib.parse.urlencode({
        "client_id":             SPOTIFY_CLIENT_ID,
        "response_type":         "code",
        "redirect_uri":          SPOTIFY_REDIRECT_URI,
        "scope":                 SPOTIFY_SCOPE,
        "code_challenge_method": "S256",
        "code_challenge":        challenge,
    })
    return redirect(f"https://accounts.spotify.com/authorize?{params}")

@app.route("/spotify/callback")
def spotify_callback():
    code  = request.args.get("code")
    error = request.args.get("error")
    if error or not code:
        state["spotify_status"]  = "Auth failed — try again"
        state["spotify_enabled"] = False
        return redirect("/?spotify=error")
    try:
        exchange_code(code, state["_pkce_verifier"])
        state["spotify_enabled"] = True
        state["spotify_status"]  = "Authenticated via PKCE"
        start_spotify_poller()
        return redirect("/?spotify=success")
    except Exception as e:
        state["spotify_status"]  = f"Token error: {e}"
        state["spotify_enabled"] = False
        return redirect("/?spotify=error")

@app.route("/spotify/status")
def spotify_status_route():
    return jsonify(
        enabled     = state["spotify_enabled"],
        status      = state["spotify_status"],
        now_playing = state["spotify_now_playing"],
        in_banner   = state["spotify_in_banner"],
    )

@app.route("/spotify/banner/toggle", methods=["POST"])
def spotify_banner_toggle():
    state["spotify_in_banner"] = not state["spotify_in_banner"]
    if state["spotify_in_banner"]:
        start_spotify_banner()
    else:
        state["spotify_banner_running"] = False
        state["spotify_caption_text"]   = ""
        state["spotify_status"]         = "Banner disabled"
    return jsonify(in_banner=state["spotify_in_banner"])

@app.route("/spotify/manual", methods=["POST"])
def spotify_manual():
    artist = request.json.get("artist", "").strip()
    song   = request.json.get("song", "").strip()
    if not artist and not song:
        return jsonify(ok=False)
    parts = [p for p in [artist, song] if p]
    state["spotify_now_playing"] = "Now Playing: " + " - ".join(parts)
    state["spotify_status"]      = "Manual track set"
    return jsonify(ok=True, now_playing=state["spotify_now_playing"])

@app.route("/spotify/logout", methods=["POST"])
def spotify_logout():
    state["spotify_token"]          = None
    state["spotify_refresh"]        = None
    state["spotify_expiry"]         = 0
    state["spotify_enabled"]        = False
    state["spotify_now_playing"]    = ""
    state["spotify_status"]         = "Not connected"
    state["spotify_in_banner"]      = False
    state["spotify_banner_running"] = False
    state["spotify_caption_text"]   = ""
    spotify_poll_running[0]         = False
    try:
        os.remove(TOKEN_FILE)
    except:
        pass
    return jsonify(ok=True)

# ── State polling (for live UI updates) ──
@app.route("/state")
def get_state():
    return jsonify(
        running             = state["running"],
        captions            = state["captions"],
        vrchat_ip           = state["vrchat_ip"],
        vrchat_port         = state["vrchat_port"],
        delay               = state["delay"],
        spotify_enabled     = state["spotify_enabled"],
        spotify_status      = state["spotify_status"],
        spotify_now_playing = state["spotify_now_playing"],
        spotify_in_banner   = state["spotify_in_banner"],
    )


# ═══════════════════════════════════════════════
#  Startup
# ═══════════════════════════════════════════════
def open_browser():
    time.sleep(1.2)
    url = f"http://127.0.0.1:{PORT}"
    # On Termux, try termux-open-url, fallback to xdg-open
    try:
        subprocess.Popen(["termux-open-url", url])
    except:
        try:
            subprocess.Popen(["xdg-open", url])
        except:
            webbrowser.open(url)

if __name__ == "__main__":
    print("=" * 52)
    print("  VRChat OSC Banner — Android Edition")
    print("  by adam77461")
    print("=" * 52)

    load_captions()

    if load_tokens() and state["spotify_refresh"]:
        state["spotify_enabled"] = True
        state["spotify_status"]  = "Session restored"
        start_spotify_poller()
        print("  Spotify session restored from cache")

    local_ip = get_local_ip()
    print(f"  Your device IP : {local_ip}")
    print(f"  Web UI         : http://127.0.0.1:{PORT}")
    print(f"  Open this URL in your Android browser")
    print("=" * 52)

    threading.Thread(target=open_browser, daemon=True).start()
    app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)