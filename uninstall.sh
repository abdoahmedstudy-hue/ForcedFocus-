#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ForcedFocus Uninstaller
# Safely removes all ForcedFocus components and restores /etc/hosts.
# Must be run as root: sudo bash uninstall.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

DAEMON_DST="/usr/local/bin/forcefocus_daemon.py"
CLI_DST="/usr/local/bin/forcefocus"
PLIST_DST="/Library/LaunchDaemons/com.forcefocus.daemon.plist"
CONFIG_DIR="/etc/forcefocus"
SOCK_PATH="/var/run/forcefocus.sock"
PLIST_LABEL="com.forcefocus.daemon"
HOSTS_PATH="/private/etc/hosts"

MARKER_BEGIN="# ──── BEGIN FORCEFOCUS ────"
MARKER_END="# ──── END FORCEFOCUS ────"

echo ""
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  ForcedFocus Uninstaller${NC}"
echo -e "${BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}✗ Must be run as root: sudo bash uninstall.sh${NC}"
    exit 1
fi

# ── Passphrase Verification ──────────────────────────────────────────────────
# Require the kill-switch passphrase to uninstall (prevents impulsive removal)
KS_HASH_FILE="${CONFIG_DIR}/ks_hash"
if [[ -f "$KS_HASH_FILE" ]]; then
    echo -e "${YELLOW}  Kill-switch passphrase required to uninstall.${NC}"
    echo ""
    read -s -p "  Passphrase: " PASSPHRASE
    echo ""

    # Verify using Python (same PBKDF2 logic as daemon)
    VERIFY_RESULT=$(/usr/bin/python3 -c "
import json, hashlib, sys
try:
    stored = json.load(open('${KS_HASH_FILE}'))
    salt = bytes.fromhex(stored['salt'])
    expected = stored['hash']
    computed = hashlib.pbkdf2_hmac('sha256', sys.stdin.buffer.read(), salt, 100000).hex()
    print('OK' if computed == expected else 'FAIL')
except Exception as e:
    print(f'ERROR:{e}')
" <<< "$PASSPHRASE" 2>&1)

    if [[ "$VERIFY_RESULT" != "OK" ]]; then
        echo -e "${RED}  ✗ Invalid passphrase. Uninstall aborted.${NC}"
        exit 1
    fi
    echo -e "${GREEN}  ✓ Passphrase verified.${NC}"
    echo ""
fi

# ── Unload LaunchDaemon ───────────────────────────────────────────────────────
echo -e "${CYAN}  Unloading LaunchDaemon...${NC}"
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    sleep 2
    echo -e "${GREEN}  ✓ Daemon unloaded.${NC}"
else
    echo -e "${YELLOW}  ⚠ Daemon was not loaded.${NC}"
fi

# ── Remove uchg flag from /etc/hosts ──────────────────────────────────────────
echo -e "${CYAN}  Removing immutable flag from /etc/hosts...${NC}"
chflags nouchg "$HOSTS_PATH" 2>/dev/null || true

# ── Strip ForcedFocus block from /etc/hosts ───────────────────────────────────
echo -e "${CYAN}  Restoring /etc/hosts...${NC}"
if grep -q "$MARKER_BEGIN" "$HOSTS_PATH" 2>/dev/null; then
    # Use sed to remove the block (inclusive of markers)
    /usr/bin/python3 -c "
from pathlib import Path
hosts = Path('${HOSTS_PATH}')
content = hosts.read_text()
lines = content.split('\n')
result = []
inside = False
for line in lines:
    if '${MARKER_BEGIN}' in line:
        inside = True
        continue
    if '${MARKER_END}' in line:
        inside = False
        continue
    if not inside:
        result.append(line)
while result and result[-1].strip() == '':
    result.pop()
hosts.write_text('\n'.join(result) + '\n')
"
    echo -e "${GREEN}  ✓ ForcedFocus entries removed from /etc/hosts.${NC}"
else
    echo -e "${GREEN}  ✓ /etc/hosts is already clean.${NC}"
fi

# ── Flush DNS ─────────────────────────────────────────────────────────────────
echo -e "${CYAN}  Flushing DNS cache...${NC}"
dscacheutil -flushcache 2>/dev/null || true
killall -HUP mDNSResponder 2>/dev/null || true
echo -e "${GREEN}  ✓ DNS cache flushed.${NC}"

# ── Remove system files ───────────────────────────────────────────────────────
echo -e "${CYAN}  Removing installed files...${NC}"

for f in "$DAEMON_DST" "$CLI_DST" "$PLIST_DST" "$SOCK_PATH"; do
    if [[ -e "$f" ]]; then
        rm -f "$f"
        echo -e "    Removed: ${f}"
    fi
done

# ── Remove config directory (preserve backups) ───────────────────────────────
if [[ -d "$CONFIG_DIR" ]]; then
    # Move any hosts backups to /tmp before deletion
    BACKUP_COUNT=$(find "$CONFIG_DIR" -name "hosts.backup.*" 2>/dev/null | wc -l | tr -d ' ')
    if [[ "$BACKUP_COUNT" -gt 0 ]]; then
        BACKUP_DST="/tmp/forcefocus_backups_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$BACKUP_DST"
        mv "$CONFIG_DIR"/hosts.backup.* "$BACKUP_DST/" 2>/dev/null || true
        echo -e "${YELLOW}  ⚠ ${BACKUP_COUNT} hosts backup(s) moved to: ${BACKUP_DST}${NC}"
    fi

    rm -rf "$CONFIG_DIR"
    echo -e "    Removed: ${CONFIG_DIR}"
fi

# ── Remove log files ─────────────────────────────────────────────────────────
for log in /var/log/forcefocus.log /var/log/forcefocus_error.log; do
    if [[ -e "$log" ]]; then
        rm -f "$log"
        echo -e "    Removed: ${log}"
    fi
done

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${GREEN}  ✓ ForcedFocus uninstalled completely.${NC}"
echo -e "${GREEN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
