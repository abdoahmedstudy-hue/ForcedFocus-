#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ForcedFocus Installer
# Deploys all components to system paths and loads the LaunchDaemon.
# Must be run as root: sudo bash install.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

# ── Color Codes ───────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON_SRC="${SCRIPT_DIR}/forcefocus_daemon.py"
CLI_SRC="${SCRIPT_DIR}/forcefocus_cli.py"
WEB_SRC="${SCRIPT_DIR}/forcefocus_web.py"
PLIST_SRC="${SCRIPT_DIR}/com.forcefocus.daemon.plist"
WEB_DIR_SRC="${SCRIPT_DIR}/web"

DAEMON_DST="/usr/local/bin/forcefocus_daemon.py"
CLI_DST="/usr/local/bin/forcefocus"
WEB_DST="/usr/local/bin/forcefocus_web.py"
PLIST_DST="/Library/LaunchDaemons/com.forcefocus.daemon.plist"
CONFIG_DIR="/etc/forcefocus"
WEB_DIR_DST="/usr/local/share/forcefocus/web"
PLIST_LABEL="com.forcefocus.daemon"

# ── Pre-flight Checks ────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  ForcedFocus Installer${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}✗ This installer must be run as root.${NC}"
    echo "  Usage: sudo bash install.sh"
    exit 1
fi

# Verify source files exist
for f in "$DAEMON_SRC" "$CLI_SRC" "$WEB_SRC" "$PLIST_SRC"; do
    if [[ ! -f "$f" ]]; then
        echo -e "${RED}✗ Missing source file: ${f}${NC}"
        exit 1
    fi
done

if [[ ! -d "$WEB_DIR_SRC" ]]; then
    echo -e "${RED}✗ Missing web directory: ${WEB_DIR_SRC}${NC}"
    exit 1
fi

# Check for Python 3 — prefer /usr/local/bin (standalone installer) over /usr/bin (Xcode CLT shim)
PYTHON_BIN=""
for candidate in /usr/local/bin/python3 /usr/bin/python3; do
    if "$candidate" --version &>/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo -e "${RED}✗ Python 3 not found.${NC}"
    echo "  Install from https://www.python.org/downloads/macos/"
    echo "  Or run: xcode-select --install"
    exit 1
fi

PYTHON_VER=$($PYTHON_BIN --version 2>&1)
echo -e "${CYAN}  Python: ${PYTHON_VER}${NC}"

# ── Unload existing daemon if running ─────────────────────────────────────────
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    echo -e "${YELLOW}  ⚠ Existing daemon detected. Unloading...${NC}"
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    sleep 1
fi

# ── Create config directory ───────────────────────────────────────────────────
echo -e "${CYAN}  Creating ${CONFIG_DIR}...${NC}"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
chown root:wheel "$CONFIG_DIR"

# Save primary user so daemon can assign socket permissions
REAL_USER="${SUDO_USER:-$USER}"
echo "$REAL_USER" > "$CONFIG_DIR/user"
chmod 644 "$CONFIG_DIR/user"

# ── Copy files ────────────────────────────────────────────────────────────────
echo -e "${CYAN}  Installing daemon → ${DAEMON_DST}${NC}"
cp "$DAEMON_SRC" "$DAEMON_DST"
chmod 700 "$DAEMON_DST"
chown root:wheel "$DAEMON_DST"

echo -e "${CYAN}  Installing CLI    → ${CLI_DST}${NC}"
cp "$CLI_SRC" "$CLI_DST"
chmod 755 "$CLI_DST"
chown root:wheel "$CLI_DST"

echo -e "${CYAN}  Installing web srv → ${WEB_DST}${NC}"
cp "$WEB_SRC" "$WEB_DST"
chmod 755 "$WEB_DST"
chown root:wheel "$WEB_DST"

echo -e "${CYAN}  Installing web UI → ${WEB_DIR_DST}${NC}"
mkdir -p "$WEB_DIR_DST"
cp -R "$WEB_DIR_SRC/"* "$WEB_DIR_DST/"
chmod -R 755 "$WEB_DIR_DST"

echo -e "${CYAN}  Installing plist  → ${PLIST_DST}${NC}"
cp "$PLIST_SRC" "$PLIST_DST"
# Update Python path in plist to match detected binary
sed -i '' "s|/usr/local/bin/python3|${PYTHON_BIN}|g" "$PLIST_DST"
chmod 644 "$PLIST_DST"
chown root:wheel "$PLIST_DST"

# ── Validate plist ────────────────────────────────────────────────────────────
echo -e "${CYAN}  Validating plist...${NC}"
if ! plutil -lint "$PLIST_DST" &>/dev/null; then
    echo -e "${RED}✗ Plist validation failed!${NC}"
    plutil -lint "$PLIST_DST"
    exit 1
fi
echo -e "${GREEN}  ✓ Plist valid.${NC}"

# ── Set kill-switch passphrase ────────────────────────────────────────────────
KS_HASH_FILE="${CONFIG_DIR}/ks_hash"
if [[ ! -f "$KS_HASH_FILE" ]]; then
    echo ""
    echo -e "${BOLD}  Set your kill-switch passphrase${NC}"
    echo -e "  This is required to unlock blocking sessions."
    echo -e "  Store it somewhere safe (password manager, written note)."
    echo ""

    # Use the CLI tool to set the key
    $PYTHON_BIN "$CLI_DST" set-key

    if [[ ! -f "$KS_HASH_FILE" ]]; then
        echo -e "${RED}✗ Kill-switch passphrase was not set. Aborting.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}  ✓ Kill-switch hash already exists. Skipping passphrase setup.${NC}"
    echo -e "    Run 'sudo forcefocus set-key' to change it."
fi

# ── Backup /etc/hosts ─────────────────────────────────────────────────────────
BACKUP="${CONFIG_DIR}/hosts.backup.$(date +%Y%m%d_%H%M%S)"
echo -e "${CYAN}  Backing up /etc/hosts → ${BACKUP}${NC}"
cp /private/etc/hosts "$BACKUP"
chmod 600 "$BACKUP"

# ── Install log rotation ──────────────────────────────────────────────────────
NEWSYSLOG_SRC="${SCRIPT_DIR}/forcefocus.newsyslog.conf"
NEWSYSLOG_DST="/etc/newsyslog.d/forcefocus.conf"
if [[ -f "$NEWSYSLOG_SRC" ]]; then
    echo -e "${CYAN}  Installing log rotation config...${NC}"
    cp "$NEWSYSLOG_SRC" "$NEWSYSLOG_DST"
    chmod 644 "$NEWSYSLOG_DST"
    echo -e "${GREEN}  ✓ Log rotation configured.${NC}"
fi

# ── Configure PF Firewall Anchor ──────────────────────────────────────────────
PF_CONF="/etc/pf.conf"
if [[ -f "$PF_CONF" ]]; then
    if ! grep -q "anchor \"forcefocus\"" "$PF_CONF"; then
        echo -e "${CYAN}  Adding forcefocus anchor to ${PF_CONF}...${NC}"
        # Safely append anchor to /etc/pf.conf
        echo "" >> "$PF_CONF"
        echo "# ForcedFocus transient rules" >> "$PF_CONF"
        echo "anchor \"forcefocus\"" >> "$PF_CONF"
        echo -e "${GREEN}  ✓ PF anchor added. Reloading PF...${NC}"
        pfctl -f "$PF_CONF" 2>/dev/null || true
    fi
fi

# ── Load the LaunchDaemon ─────────────────────────────────────────────────────
echo -e "${CYAN}  Loading LaunchDaemon...${NC}"
launchctl load -w "$PLIST_DST"
sleep 2

# Verify it's running
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    echo -e "${GREEN}  ✓ Daemon loaded and running.${NC}"
else
    echo -e "${RED}  ✗ Daemon failed to start. Check /var/log/forcefocus_error.log${NC}"
    exit 1
fi

# ── Clean up legacy Web UI LaunchAgent ────────────────────────────────────────
REAL_USER="${SUDO_USER:-$USER}"
REAL_HOME=$(eval echo "~${REAL_USER}")
WEB_PLIST_LEGACY="${REAL_HOME}/Library/LaunchAgents/com.forcefocus.web.plist"
if [[ -f "$WEB_PLIST_LEGACY" ]]; then
    sudo -u "$REAL_USER" launchctl unload "$WEB_PLIST_LEGACY" 2>/dev/null || true
    rm -f "$WEB_PLIST_LEGACY"
    echo -e "${CYAN}  Cleaned up legacy web LaunchAgent.${NC}"
fi
pkill -f "forcefocus_web.py" 2>/dev/null || true

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ ForcedFocus installed successfully!${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
echo -e "  ${BOLD}What starts automatically:${NC}"
echo -e "    • Daemon (root)  — blocks sites + web UI (http://localhost:7070)"
echo ""
echo -e "  ${BOLD}Quick Start:${NC}"
echo -e "    forcefocus start --duration 120   # Block for 2 hours"
echo -e "    forcefocus status                 # Check session"
echo -e "    forcefocus stop --key 'phrase'    # Unlock (20-min delay)"
echo ""
echo -e "  ${BOLD}Logs:${NC}"
echo -e "    tail -f /var/log/forcefocus.log"
echo ""
