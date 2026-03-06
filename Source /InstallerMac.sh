#!/bin/bash
# ─────────────────────────────────────────────────────────
#  VRChat OSC Banner — macOS Installer
#  by adam77461
#  https://github.com/adam77461/OSC-Banner-for-vrchat
#
#  Usage: bash install.sh
# ─────────────────────────────────────────────────────────

set -e

APP_NAME="VRChat OSC Banner"
INSTALL_DIR="$HOME/.vrchat-osc-banner"
APP_DIR="$INSTALL_DIR/app"
VENV_DIR="$INSTALL_DIR/venv"
MAIN_URL="https://raw.githubusercontent.com/adam77461/OSC-Banner-for-vrchat/main/Source%20/main.py"
LAUNCHER="$INSTALL_DIR/launch.sh"
DESKTOP_APP="$HOME/Desktop/VRChat OSC Banner.command"
APP_SUPPORT="$HOME/Applications/VRChat OSC Banner.command"

# ── Colors ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

clear
echo ""
echo -e "${CYAN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║        VRChat OSC Banner — macOS Installer       ║"
echo "  ║                  by adam77461                    ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"
echo ""

# ── Step 1: Check macOS ──
echo -e "${BOLD}[1/6] Checking system...${NC}"

OS=$(uname -s)
if [ "$OS" != "Darwin" ]; then
    echo -e "${RED}  ✗ This installer is for macOS only.${NC}"
    exit 1
fi

ARCH=$(uname -m)
echo -e "  ✓ macOS detected (${ARCH})"

# Check for curl
if ! command -v curl &>/dev/null; then
    echo -e "${RED}  ✗ curl not found. This is unusual on macOS.${NC}"
    exit 1
fi
echo -e "  ✓ curl found"
echo ""

# ── Step 2: Check / Install Python 3 ──
echo -e "${BOLD}[2/6] Checking Python 3...${NC}"

PYTHON=""

# Prefer python3 from brew or system
for candidate in python3 python3.11 python3.12 python3.10; do
    if command -v "$candidate" &>/dev/null; then
        VER=$("$candidate" --version 2>&1 | awk '{print $2}')
        MAJOR=$(echo "$VER" | cut -d. -f1)
        MINOR=$(echo "$VER" | cut -d. -f2)
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 10 ]; then
            PYTHON=$(command -v "$candidate")
            echo -e "  ✓ Found Python $VER at $PYTHON"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo -e "${YELLOW}  Python 3.10+ not found. Attempting to install via Homebrew...${NC}"

    if ! command -v brew &>/dev/null; then
        echo -e "${YELLOW}  Homebrew not found. Installing Homebrew first...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

        # Add brew to path for Apple Silicon
        if [ -f "/opt/homebrew/bin/brew" ]; then
            eval "$(/opt/homebrew/bin/brew shellenv)"
        fi
    fi

    echo -e "  Installing Python 3.11 via Homebrew..."
    brew install python@3.11

    PYTHON=$(command -v python3.11 || command -v python3)
    if [ -z "$PYTHON" ]; then
        echo -e "${RED}  ✗ Python installation failed. Please install Python 3.10+ manually from python.org${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓ Python installed at $PYTHON${NC}"
fi
echo ""

# ── Step 3: Create install directory + virtual environment ──
echo -e "${BOLD}[3/6] Setting up environment...${NC}"

mkdir -p "$APP_DIR"
echo -e "  ✓ Install directory: $INSTALL_DIR"

# Create a virtual environment so we don't pollute system Python
"$PYTHON" -m venv "$VENV_DIR"
VENV_PYTHON="$VENV_DIR/bin/python"
VENV_PIP="$VENV_DIR/bin/pip"
echo -e "  ✓ Virtual environment created"
echo ""

# ── Step 4: Install dependencies ──
echo -e "${BOLD}[4/6] Installing dependencies...${NC}"
echo -e "  This may take a minute..."
echo ""

"$VENV_PIP" install --quiet --upgrade pip
"$VENV_PIP" install --quiet customtkinter python-osc

echo -e "  ${GREEN}✓ customtkinter${NC}"
echo -e "  ${GREEN}✓ python-osc${NC}"
echo ""

# ── Step 5: Download main.py ──
echo -e "${BOLD}[5/6] Downloading VRChat OSC Banner...${NC}"

curl -L --progress-bar "$MAIN_URL" -o "$APP_DIR/main.py"

if [ ! -f "$APP_DIR/main.py" ]; then
    echo -e "${RED}  ✗ Download failed. Check your internet connection.${NC}"
    exit 1
fi

echo -e "  ${GREEN}✓ main.py downloaded${NC}"
echo ""

# ── Step 6: Create launcher + shortcuts ──
echo -e "${BOLD}[6/6] Creating launcher and shortcuts...${NC}"

# Create the launcher script
cat > "$LAUNCHER" << EOF
#!/bin/bash
cd "$APP_DIR"
"$VENV_PYTHON" "$APP_DIR/main.py"
EOF
chmod +x "$LAUNCHER"

# Desktop .command file (double-clickable on Mac)
cat > "$DESKTOP_APP" << EOF
#!/bin/bash
cd "$APP_DIR"
"$VENV_PYTHON" "$APP_DIR/main.py"
EOF
chmod +x "$DESKTOP_APP"
echo -e "  ✓ Desktop shortcut created: ~/Desktop/VRChat OSC Banner.command"

# ~/Applications shortcut
mkdir -p "$HOME/Applications"
cat > "$APP_SUPPORT" << EOF
#!/bin/bash
cd "$APP_DIR"
"$VENV_PYTHON" "$APP_DIR/main.py"
EOF
chmod +x "$APP_SUPPORT"
echo -e "  ✓ Applications shortcut created: ~/Applications/VRChat OSC Banner.command"

# Create uninstaller
UNINSTALLER="$INSTALL_DIR/uninstall.sh"
cat > "$UNINSTALLER" << EOF
#!/bin/bash
echo "Removing VRChat OSC Banner..."
rm -rf "$INSTALL_DIR"
rm -f "$DESKTOP_APP"
rm -f "$APP_SUPPORT"
echo "Done. VRChat OSC Banner has been removed."
EOF
chmod +x "$UNINSTALLER"
echo -e "  ✓ Uninstaller created"
echo ""

# ── Fix macOS Gatekeeper for .command files ──
xattr -cr "$DESKTOP_APP" 2>/dev/null || true
xattr -cr "$APP_SUPPORT" 2>/dev/null || true

# ── Done ──
echo -e "${GREEN}${BOLD}"
echo "  ╔══════════════════════════════════════════════════╗"
echo "  ║  ✓ Installation complete!                        ║"
echo "  ║                                                  ║"
echo "  ║  Launch from your Desktop:                       ║"
echo "  ║  'VRChat OSC Banner.command'                     ║"
echo "  ║                                                  ║"
echo "  ║  Or run manually:                                ║"
echo "  ║  bash ~/.vrchat-osc-banner/launch.sh             ║"
echo "  ║                                                  ║"
echo "  ║  To uninstall:                                   ║"
echo "  ║  bash ~/.vrchat-osc-banner/uninstall.sh          ║"
echo "  ╚══════════════════════════════════════════════════╝"
echo -e "${NC}"

# Offer to launch now
read -r -p "  Launch VRChat OSC Banner now? (y/n): " LAUNCH
if [[ "$LAUNCH" =~ ^[Yy]$ ]]; then
    echo ""
    echo -e "  ${CYAN}Launching...${NC}"
    bash "$LAUNCHER"
fi

echo ""
