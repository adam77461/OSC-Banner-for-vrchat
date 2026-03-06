#!/data/data/com.termux/files/usr/bin/bash
# ─────────────────────────────────────────────────────────
#  VRChat OSC Banner — Android (Termux) Installer
#  by adam77461
#  https://github.com/adam77461/OSC-Banner-for-vrchat
#
#  Usage (in Termux):
#    curl -fsSL https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/android/install-termux.sh | bash
#  Or:
#    bash install-termux.sh
# ─────────────────────────────────────────────────────────

set -e

REPO_RAW="https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/android"
INSTALL_DIR="$HOME/vrchat-osc-banner"
APP_DIR="$INSTALL_DIR/app"
TEMPLATES_DIR="$APP_DIR/templates"
LAUNCHER="$INSTALL_DIR/launch.sh"

# ── Colors ──
R='\033[0;31m'
G='\033[0;32m'
Y='\033[1;33m'
C='\033[0;36m'
B='\033[1m'
N='\033[0m'

clear
echo ""
echo -e "${C}${B}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║    VRChat OSC Banner — Android Termux Installer  ║"
echo "  ║                  by adam77461                    ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${N}"
echo ""

# ── Verify Termux ──
if [ ! -d "/data/data/com.termux" ]; then
    echo -e "${R}  ✗ This installer is for Termux on Android only.${N}"
    echo "    Download Termux from F-Droid: https://f-droid.org"
    exit 1
fi

echo -e "${B}[1/7] Requesting storage permission...${N}"
# Allow Termux to access shared storage
termux-setup-storage 2>/dev/null || true
echo -e "  ${G}✓ Storage ready${N}"
echo ""

# ── Update packages ──
echo -e "${B}[2/7] Updating package lists...${N}"
pkg update -y -q 2>/dev/null || apt-get update -y -q 2>/dev/null || true
echo -e "  ${G}✓ Package lists updated${N}"
echo ""

# ── Install system deps ──
echo -e "${B}[3/7] Installing system packages...${N}"
echo "  Installing: python, pip, nmap, iproute2..."

pkg install -y python python-pip nmap iproute2 2>/dev/null || \
  apt-get install -y python python-pip nmap iproute2 2>/dev/null || true

# Verify python
if ! command -v python &>/dev/null && ! command -v python3 &>/dev/null; then
    echo -e "${R}  ✗ Python failed to install. Try: pkg install python${N}"
    exit 1
fi

PYTHON=$(command -v python3 || command -v python)
echo -e "  ${G}✓ Python: $(${PYTHON} --version)${N}"
echo -e "  ${G}✓ System packages installed${N}"
echo ""

# ── Install Python packages ──
echo -e "${B}[4/7] Installing Python packages...${N}"
echo "  Installing: flask, python-osc, requests..."

$PYTHON -m pip install --quiet --upgrade pip
$PYTHON -m pip install --quiet flask python-osc requests

echo -e "  ${G}✓ flask${N}"
echo -e "  ${G}✓ python-osc${N}"
echo -e "  ${G}✓ requests${N}"
echo ""

# ── Create directories ──
echo -e "${B}[5/7] Setting up app directory...${N}"
mkdir -p "$APP_DIR"
mkdir -p "$TEMPLATES_DIR"
echo -e "  ✓ $INSTALL_DIR"
echo ""

# ── Download app files ──
echo -e "${B}[6/7] Downloading app files...${N}"

download_file() {
    local url="$1"
    local dest="$2"
    echo -e "  Downloading: $(basename $dest)..."
    if command -v curl &>/dev/null; then
        curl -fsSL "$url" -o "$dest"
    elif command -v wget &>/dev/null; then
        wget -q "$url" -O "$dest"
    else
        echo -e "${R}  ✗ Neither curl nor wget found. Install with: pkg install curl${N}"
        exit 1
    fi
    if [ -f "$dest" ] && [ -s "$dest" ]; then
        echo -e "  ${G}✓ $(basename $dest)${N}"
    else
        echo -e "${R}  ✗ Failed to download $(basename $dest)${N}"
        exit 1
    fi
}

download_file "$REPO_RAW/main.py"              "$APP_DIR/main.py"
download_file "$REPO_RAW/templates/index.html" "$TEMPLATES_DIR/index.html"

echo ""

# ── Create launcher ──
echo -e "${B}[7/7] Creating launcher...${N}"

cat > "$LAUNCHER" << LAUNCH_EOF
#!/data/data/com.termux/files/usr/bin/bash
# VRChat OSC Banner — Launcher
cd "$APP_DIR"
echo ""
echo "  Starting VRChat OSC Banner..."
echo "  Open your browser and go to: http://127.0.0.1:5000"
echo ""
$PYTHON "$APP_DIR/main.py"
LAUNCH_EOF

chmod +x "$LAUNCHER"

# Create a short alias command
ALIAS_FILE="$HOME/.bashrc"
ALIAS_LINE="alias vrchat-banner='bash $LAUNCHER'"

if ! grep -q "vrchat-banner" "$ALIAS_FILE" 2>/dev/null; then
    echo "" >> "$ALIAS_FILE"
    echo "# VRChat OSC Banner" >> "$ALIAS_FILE"
    echo "$ALIAS_LINE" >> "$ALIAS_FILE"
fi

# Also add to .profile for good measure
PROFILE="$HOME/.profile"
if ! grep -q "vrchat-banner" "$PROFILE" 2>/dev/null; then
    echo "" >> "$PROFILE"
    echo "# VRChat OSC Banner" >> "$PROFILE"
    echo "$ALIAS_LINE" >> "$PROFILE"
fi

echo -e "  ${G}✓ Launcher: $LAUNCHER${N}"
echo -e "  ${G}✓ Alias 'vrchat-banner' added${N}"
echo ""

# ── Create uninstaller ──
UNINSTALLER="$INSTALL_DIR/uninstall.sh"
cat > "$UNINSTALLER" << UNINSTALL_EOF
#!/data/data/com.termux/files/usr/bin/bash
echo "Removing VRChat OSC Banner..."
rm -rf "$INSTALL_DIR"
sed -i '/vrchat-banner/d' "$HOME/.bashrc" 2>/dev/null
sed -i '/VRChat OSC Banner/d' "$HOME/.bashrc" 2>/dev/null
sed -i '/vrchat-banner/d' "$HOME/.profile" 2>/dev/null
echo "Done. VRChat OSC Banner has been removed."
UNINSTALL_EOF
chmod +x "$UNINSTALLER"

# ── Firewall / port note ──
echo -e "${Y}  ℹ️  Network note:${N}"
echo "  Make sure VRChat on your headset has OSC enabled:"
echo "  Action Menu → Options → OSC → Enable"
echo ""
echo "  The auto-detect feature will scan your local network"
echo "  to find your PC/headset running VRChat."
echo ""

# ── Done ──
echo -e "${G}${B}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ✓ Installation complete!                        ║"
echo "  ║                                                  ║"
echo "  ║  To launch:                                      ║"
echo "  ║    Type:  vrchat-banner                          ║"
echo "  ║    Or:    bash ~/vrchat-osc-banner/launch.sh     ║"
echo "  ║                                                  ║"
echo "  ║  Then open in your browser:                      ║"
echo "  ║    http://127.0.0.1:5000                         ║"
echo "  ║                                                  ║"
echo "  ║  To uninstall:                                   ║"
echo "  ║    bash ~/vrchat-osc-banner/uninstall.sh         ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${N}"

# ── Offer to launch ──
read -r -p "  Launch now? (y/n): " GO
if [[ "$GO" =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "  ${C}Open your Android browser and go to: http://127.0.0.1:5000${N}"
    echo ""
    source "$HOME/.bashrc" 2>/dev/null || true
    bash "$LAUNCHER"
fi

echo ""