#!/usr/bin/env python3
"""
ForcedFocus CLI — Command-line interface for the ForcedFocus daemon.

Usage:
    forcefocus start [--duration MINUTES] [--mode blacklist|whitelist]
    forcefocus stop  --key PASSPHRASE       Request delayed unlock (20 min)
    forcefocus status                       Show current session state
    forcefocus set-key                      Set/change kill-switch passphrase
    forcefocus web                          Start web UI on localhost:7070
"""

import os
import sys
import subprocess
import json
import socket
import hashlib
import getpass
import argparse
from pathlib import Path

SOCK_PATH    = "/var/run/forcefocus.sock"
KS_HASH_FILE = Path("/etc/forcefocus/ks_hash")
CONFIG_DIR   = Path("/etc/forcefocus")

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SOCKET COMMUNICATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def send_command(cmd: dict) -> dict:
    """Send a JSON command to the daemon over the Unix socket."""
    if not os.path.exists(SOCK_PATH):
        print("✗ Daemon is not running (socket not found).", file=sys.stderr)
        print("  Start it with: sudo launchctl load /Library/LaunchDaemons/com.forcefocus.daemon.plist")
        sys.exit(1)

    try:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect(SOCK_PATH)
        sock.sendall(json.dumps(cmd).encode("utf-8"))
        raw = sock.recv(8192).decode("utf-8")
        sock.close()
        return json.loads(raw)
    except ConnectionRefusedError:
        print("✗ Connection refused. Is the daemon running?", file=sys.stderr)
        sys.exit(1)
    except socket.timeout:
        print("✗ Daemon did not respond in time.", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"✗ Communication error: {exc}", file=sys.stderr)
        sys.exit(1)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# COMMANDS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def cmd_start(args):
    """Start a time-bound blocking session."""
    duration = args.duration
    mode = args.mode
    if duration <= 0:
        print("✗ Duration must be a positive number of minutes.", file=sys.stderr)
        sys.exit(1)

    print(f"⏳ Starting {mode} session for {duration} minutes...")
    resp = send_command({"action": "start", "duration_minutes": duration, "mode": mode})

    status = resp.get("status")
    msg    = resp.get("message", "")

    if status == "ok":
        print(f"✓ {msg}")
        print(f"  Use 'forcefocus status' to check remaining time.")
    elif status == "already_active":
        print(f"⚠ {msg}")
    else:
        print(f"✗ {msg}", file=sys.stderr)
        sys.exit(1)


def cmd_stop(args):
    """Request a delayed unlock (20-minute delay)."""
    key = args.key
    if not key:
        key = getpass.getpass("Kill-switch passphrase: ")

    print("🔐 Sending unlock request to daemon...")
    resp = send_command({"action": "stop", "key": key})

    status = resp.get("status")
    msg    = resp.get("message", "")

    if status == "pending":
        print(f"⏱  {msg}")
        print(f"   Blocking remains active for 20 more minutes.")
        print(f"   This cannot be cancelled. Use this time wisely.")
    elif status == "ok":
        print(f"✓ {msg}")
    elif status == "error":
        print(f"✗ {msg}", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"? {msg}")


def cmd_status(_args):
    """Print current daemon/session state."""
    resp = send_command({"action": "status"})

    status = resp.get("status")
    active = resp.get("active", False)

    if not active:
        print("○ ForcedFocus is idle — no active blocking session.")
        return

    mode      = resp.get("mode", "?")
    expires   = resp.get("expires_at", "?")
    rem_secs  = resp.get("remaining_seconds", 0)
    rem_min   = rem_secs // 60
    rem_sec   = rem_secs % 60
    count     = resp.get("domains_count", 0)
    pending   = resp.get("pending_unlock")

    print("━" * 50)
    print(f"  ● ForcedFocus — ACTIVE ({mode.upper()})")
    print("━" * 50)
    print(f"  Mode            : {mode}")
    print(f"  Domains         : {count}")
    print(f"  Session expires : {expires}")
    print(f"  Time remaining  : {rem_min}m {rem_sec}s")
    if pending:
        print(f"  ⏱ Unlock pending : {pending}")
    else:
        print(f"  Unlock pending  : No")
    print("━" * 50)


def cmd_set_key(_args):
    """Set or change the kill-switch passphrase."""
    if os.geteuid() != 0:
        print("✗ Must run as root: sudo forcefocus set-key", file=sys.stderr)
        sys.exit(1)

    print("━" * 50)
    print("  ForcedFocus — Set Kill-Switch Passphrase")
    print("━" * 50)
    print()
    print("  This passphrase is required to unlock a blocking session.")
    print("  It is stored as a PBKDF2-HMAC-SHA256 hash (never plaintext).")
    print("  Keep it somewhere safe (e.g., a hardware password manager).")
    print()

    p1 = getpass.getpass("  New passphrase: ")
    p2 = getpass.getpass("  Confirm:        ")

    if p1 != p2:
        print("\n✗ Passphrases do not match.", file=sys.stderr)
        sys.exit(1)

    if len(p1) < 8:
        print("\n✗ Passphrase must be at least 8 characters.", file=sys.stderr)
        sys.exit(1)

    # Generate salt and hash
    salt = os.urandom(32)
    key_hash = hashlib.pbkdf2_hmac(
        "sha256",
        p1.encode("utf-8"),
        salt,
        100_000,
    ).hex()

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    KS_HASH_FILE.write_text(json.dumps({
        "salt": salt.hex(),
        "hash": key_hash,
        "iterations": 100_000,
        "algorithm": "pbkdf2_hmac_sha256",
    }, indent=2))
    os.chmod(str(KS_HASH_FILE), 0o600)

    print()
    print("✓ Kill-switch passphrase set successfully.")
    print(f"  Hash stored at: {KS_HASH_FILE}")


def cmd_web(_args):
    """Start the web UI server."""
    web_script = Path("/usr/local/bin/forcefocus_web.py")
    if not web_script.exists():
        # Try local development path
        web_script = Path(__file__).parent / "forcefocus_web.py"
    if not web_script.exists():
        print("✗ Web server script not found.", file=sys.stderr)
        sys.exit(1)

    print("🌐 Starting ForcedFocus Web UI...")
    print("   Open http://localhost:7070 in your browser.")
    print("   Press Ctrl+C to stop.\n")
    try:
        subprocess.run([sys.executable, str(web_script)])
    except KeyboardInterrupt:
        print("\nWeb server stopped.")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ARGUMENT PARSER
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="forcefocus",
        description="ForcedFocus — Unbreakable macOS website blocker.",
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # start
    p_start = sub.add_parser("start", help="Start a blocking session")
    p_start.add_argument(
        "--duration", "-d",
        type=int,
        default=120,
        metavar="MINUTES",
        help="Session duration in minutes (default: 120)",
    )
    p_start.add_argument(
        "--mode", "-m",
        type=str,
        default="blacklist",
        choices=["blacklist", "whitelist"],
        help="Blocking mode (default: blacklist)",
    )
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = sub.add_parser("stop", help="Request delayed unlock (20-min delay)")
    p_stop.add_argument(
        "--key", "-k",
        type=str,
        default="",
        help="Kill-switch passphrase (prompted if omitted)",
    )
    p_stop.set_defaults(func=cmd_stop)

    # status
    p_status = sub.add_parser("status", help="Show current session state")
    p_status.set_defaults(func=cmd_status)

    # set-key
    p_setkey = sub.add_parser("set-key", help="Set/change kill-switch passphrase")
    p_setkey.set_defaults(func=cmd_set_key)

    # web
    p_web = sub.add_parser("web", help="Start web UI on localhost:7070")
    p_web.set_defaults(func=cmd_web)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
