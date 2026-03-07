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
import secrets as _secrets
import http.server
import socketserver
from datetime import datetime
import customtkinter as ctk
from tkinter import filedialog
from pythonosc.udp_client import SimpleUDPClient

# ---------------- CONFIG ----------------
VRCHAT_IP = "192.168.1.87"
VRCHAT_PORT = 9000
DEFAULT_FILE = "captions.json"
TOKEN_FILE = "spotify_token.json"

SPOTIFY_CLIENT_ID = "690ecc75dfae468e9e8dc3a4697609fc"
# No client secret needed — using PKCE flow (safe to deploy publicly)
SPOTIFY_REDIRECT_URI = "http://127.0.0.1:8888/callback"
SPOTIFY_SCOPE = "user-read-currently-playing user-read-playback-state"

osc = SimpleUDPClient(VRCHAT_IP, VRCHAT_PORT)

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

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


def reconnect_osc(ip, port):
    global osc
    osc = SimpleUDPClient(ip, int(port))


# ---------------- OSC ----------------
def format_caption(text, padding=3):
    width = len(text) + padding * 2
    border = "~" * width
    middle = " " * padding + text + " " * padding
    return f"{border}\n{middle}\n{border}"

def send_caption(text):
    formatted = format_caption(text)
    osc.send_message("/chatbox/input", [formatted, True, False])


# ---------------- JSON ----------------
def load_json(file_path):
    global captions, current_file
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            captions = data.get("captions", [])
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
    """Generate a code_verifier and its SHA-256 code_challenge."""
    verifier = _secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    import base64
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

        if caption == "{time}":
            text = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        else:
            text = caption

        app.after(0, lambda t=text, i=idx: update_now_sending(t, i))
        send_caption(text)
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
    for w in list_inner.winfo_children():
        w.destroy()
    row_frames.clear()

    for i, c in enumerate(captions):
        is_time = c == "{time}"
        row = ctk.CTkFrame(list_inner, fg_color=CARD, corner_radius=8, height=38)
        row.pack(fill="x", pady=2, padx=0)
        row.pack_propagate(False)
        row_frames.append(row)

        icon = "⏰" if is_time else "💬"
        icon_lbl = ctk.CTkLabel(row, text=icon, font=("Segoe UI Emoji", 13),
                                 width=28, text_color=TEXT_MUTED)
        icon_lbl.place(x=8, rely=0.5, anchor="w")

        display_text = c if len(c) <= 50 else c[:47] + "..."
        text_lbl = ctk.CTkLabel(row, text=display_text, font=("Segoe UI", 12),
                                 text_color=TEXT_PRIMARY, anchor="w")
        text_lbl.place(x=36, rely=0.5, anchor="w")

        del_btn = ctk.CTkButton(
            row, text="✕", width=24, height=24,
            font=("Segoe UI", 10, "bold"),
            fg_color="transparent", hover_color="#374151",
            text_color=TEXT_MUTED, corner_radius=6,
            command=lambda idx=i: delete_caption(idx)
        )
        del_btn.place(relx=1.0, x=-6, rely=0.5, anchor="e")

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
        captions.append(text)
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
        reconnect_osc(ip, port)
        footer_target.configure(text=f"->  {ip}:{port}")
        ip_status.configure(text="Applied!", text_color=SUCCESS)
        app.after(2000, lambda: ip_status.configure(text=""))
    except Exception:
        ip_status.configure(text="Failed", text_color=DANGER)


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

# ── Header ──
header = ctk.CTkFrame(app, fg_color="#0d1117", corner_radius=0, height=56)
header.pack(fill="x")
header.pack_propagate(False)

ctk.CTkLabel(header, text="●", font=("Segoe UI", 18), text_color=ACCENT).place(x=20, rely=0.5, anchor="w")
ctk.CTkLabel(header, text="OSC Banner", font=("Segoe UI", 15, "bold"), text_color=TEXT_PRIMARY).place(x=42, rely=0.5, anchor="w")
ctk.CTkLabel(header, text="VRChat Chatbox Controller", font=("Segoe UI", 11), text_color=TEXT_MUTED).place(x=152, rely=0.5, anchor="w")

status_frame = ctk.CTkFrame(header, fg_color="#1f2937", corner_radius=20, height=28)
status_frame.place(relx=1.0, x=-16, rely=0.5, anchor="e")
status_frame.pack_propagate(False)
status_dot = ctk.CTkLabel(status_frame, text="●", font=("Segoe UI", 11), text_color=DANGER, width=16)
status_dot.pack(side="left", padx=(8, 2))
status_text = ctk.CTkLabel(status_frame, text="Stopped", font=("Segoe UI", 11, "bold"), text_color=DANGER, width=56)
status_text.pack(side="left", padx=(0, 10))

# ── Body ──
body = ctk.CTkFrame(app, fg_color=SURFACE)
body.pack(fill="both", expand=True, padx=20, pady=14)

# ── Start / Stop Buttons (top) ──
btn_frame = ctk.CTkFrame(body, fg_color="transparent")
btn_frame.pack(fill="x", pady=(0, 8))

start_btn = ctk.CTkButton(
    btn_frame, text="  Start", font=("Segoe UI", 13, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=10, height=42,
    command=start_loop
)
start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

stop_btn = ctk.CTkButton(
    btn_frame, text="  Stop", font=("Segoe UI", 13, "bold"),
    fg_color="#7f1d1d", hover_color="#991b1b", corner_radius=10, height=42,
    state="disabled", command=stop_loop
)
stop_btn.pack(side="left", expand=True, fill="x", padx=5)

# ── Now Sending ──
now_card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=58)
now_card.pack(fill="x", pady=(0, 8))
now_card.pack_propagate(False)
ctk.CTkLabel(now_card, text="NOW SENDING", font=("Segoe UI", 9, "bold"), text_color=TEXT_MUTED).place(x=14, y=9)
now_label = ctk.CTkLabel(now_card, text="—", font=("Segoe UI", 13, "bold"), text_color=ACCENT, anchor="w")
now_label.place(x=14, y=29)

# ── Spotify Card ──
spotify_card = ctk.CTkFrame(body, fg_color="#0d1f12", corner_radius=12, height=110,
                             border_width=1, border_color="#1c3828")
spotify_card.pack(fill="x", pady=(0, 8))
spotify_card.pack_propagate(False)

# Top row: icon + label + login btn
sp_header = ctk.CTkFrame(spotify_card, fg_color="transparent")
sp_header.place(x=14, y=10)
ctk.CTkLabel(sp_header, text="♫", font=("Segoe UI", 15), text_color=SPOTIFY_GREEN).pack(side="left", padx=(0, 5))
ctk.CTkLabel(sp_header, text="SPOTIFY", font=("Segoe UI", 9, "bold"), text_color=SPOTIFY_GREEN).pack(side="left")

spotify_login_btn = ctk.CTkButton(
    spotify_card, text="Login with Spotify", width=152, height=28,
    font=("Segoe UI", 11, "bold"),
    fg_color=SPOTIFY_GREEN, hover_color="#17a349", text_color="#000000",
    corner_radius=20, command=do_spotify_login
)
spotify_login_btn.place(relx=1.0, x=-14, y=10)

# Status + track
spotify_status_label = ctk.CTkLabel(spotify_card, text="Not connected — click Login to authorize",
                                     font=("Segoe UI", 9), text_color=TEXT_MUTED)
spotify_status_label.place(x=14, y=32)

spotify_track_label = ctk.CTkLabel(spotify_card, text="—",
                                    font=("Segoe UI", 11, "bold"),
                                    text_color=TEXT_MUTED, anchor="w", wraplength=310)
spotify_track_label.place(x=14, y=52)

# Bottom row: manual artist/song + Add to Banner btn
sp_bottom = ctk.CTkFrame(spotify_card, fg_color="transparent")
sp_bottom.place(x=14, y=78, relwidth=0.97)

manual_artist_entry = ctk.CTkEntry(
    sp_bottom, placeholder_text="Artist",
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=110, height=24, corner_radius=6
)
manual_artist_entry.pack(side="left", padx=(0, 4))

manual_song_entry = ctk.CTkEntry(
    sp_bottom, placeholder_text="Song",
    font=("Segoe UI", 11), fg_color=SURFACE, border_color=BORDER,
    border_width=1, text_color=TEXT_PRIMARY,
    placeholder_text_color=TEXT_MUTED, width=110, height=24, corner_radius=6
)
manual_song_entry.pack(side="left", padx=(0, 6))

ctk.CTkButton(
    sp_bottom, text="Set Manual", width=84, height=24,
    font=("Segoe UI", 10), fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_PRIMARY, corner_radius=6,
    command=use_manual_track
).pack(side="left", padx=(0, 6))

spotify_banner_btn = ctk.CTkButton(
    sp_bottom, text="+ Add to Banner", width=116, height=24,
    font=("Segoe UI", 10, "bold"),
    fg_color=BORDER, hover_color="#4b5563",
    text_color=TEXT_PRIMARY, corner_radius=6,
    command=toggle_spotify_banner
)
spotify_banner_btn.pack(side="left")

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
input_frame = ctk.CTkFrame(body, fg_color=CARD, corner_radius=12, height=50)
input_frame.pack(fill="x", pady=(0, 8))
input_frame.pack_propagate(False)

entry = ctk.CTkEntry(
    input_frame,
    placeholder_text="New caption… use {time} for clock",
    font=("Segoe UI", 12),
    fg_color="transparent", border_width=0,
    text_color=TEXT_PRIMARY, placeholder_text_color=TEXT_MUTED
)
entry.place(x=12, rely=0.5, anchor="w", relwidth=0.82)
entry.bind("<Return>", on_entry_return)

add_btn = ctk.CTkButton(
    input_frame, text="+ Add", width=76, height=32,
    font=("Segoe UI", 12, "bold"),
    fg_color=ACCENT, hover_color="#1d4ed8", corner_radius=8,
    command=add_caption
)
add_btn.place(relx=1.0, x=-10, rely=0.5, anchor="e")

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



sec_frame = ctk.CTkFrame(body, fg_color="transparent")
sec_frame.pack(fill="x", pady=(8, 0))

load_btn = ctk.CTkButton(
    sec_frame, text="Load JSON", font=("Segoe UI", 11),
    fg_color=BORDER, hover_color="#4b5563", corner_radius=8, height=32,
    text_color=TEXT_PRIMARY, command=load_file
)
load_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

clear_btn = ctk.CTkButton(
    sec_frame, text="Clear All", font=("Segoe UI", 11),
    fg_color="transparent", hover_color="#374151", corner_radius=8, height=32,
    text_color=TEXT_MUTED, border_width=1, border_color=BORDER,
    command=clear_all
)
clear_btn.pack(side="left", expand=True, fill="x", padx=5)

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
    captions = ["sleeping zzz", "{time}", "miku miku beam"]
    save_json()
    refresh_list()

# Restore saved Spotify session if available
if load_tokens() and spotify_refresh_token:
    spotify_enabled = True
    spotify_login_btn.configure(text="Connected!", fg_color="#166534")
    spotify_status_label.configure(text="Session restored — polling every 5s", text_color=SUCCESS)
    start_spotify_poller()

app.mainloop()
