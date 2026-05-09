#!/usr/bin/env python3
"""
ForcedFocus Daemon v2 — Root-level macOS website blocker.

Supports blacklist mode (block listed sites) and whitelist mode
(allow ONLY listed sites by redirecting DNS + pinning IPs).
"""

import os
import sys
import json
import time
import signal
import socket
import struct
import select
import hashlib
import hmac
import logging
import threading
import subprocess
import mimetypes
from pathlib import Path
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, unquote

def get_continuous_time() -> float:
    # CLOCK_MONOTONIC_RAW on macOS maps to mach_continuous_time (includes sleep time)
    return time.clock_gettime(time.CLOCK_MONOTONIC_RAW)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

CONFIG_DIR        = Path("/etc/forcefocus")
SESSION_LOCK      = CONFIG_DIR / "session.lock"
KS_HASH_FILE      = CONFIG_DIR / "ks_hash"
LISTS_FILE        = CONFIG_DIR / "lists.json"
SOCK_PATH         = "/var/run/forcefocus.sock"
HOSTS_PATH        = Path("/private/etc/hosts")
WEB_HOST          = "127.0.0.1"
WEB_PORT          = 7070
WEB_DIR           = Path("/usr/local/share/forcefocus/web")

MARKER_BEGIN      = "# ──── BEGIN FORCEFOCUS ────"
MARKER_END        = "# ──── END FORCEFOCUS ────"

WATCHDOG_INTERVAL = 0.25
SOCKET_TIMEOUT    = 1.0
DELAYED_UNLOCK_S  = 20 * 60

# Subdomains to auto-resolve in whitelist mode
WHITELIST_PREFIXES = ["", "www.", "m.", "api.", "cdn.", "static."]

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DEFAULT BLOCKLIST (fallback when lists.json blacklist is empty)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

DEFAULT_BLOCKLIST = {
    "social_media": [
        "reddit.com", "www.reddit.com", "old.reddit.com",
        "twitter.com", "www.twitter.com", "x.com", "www.x.com",
        "facebook.com", "www.facebook.com", "m.facebook.com",
        "instagram.com", "www.instagram.com",
        "tiktok.com", "www.tiktok.com", "snapchat.com", "www.snapchat.com",
    ],
    "video_streaming": [
        "youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be",
        "twitch.tv", "www.twitch.tv",
    ],
    "news_entertainment": [
        "news.ycombinator.com", "9gag.com", "www.9gag.com",
        "buzzfeed.com", "www.buzzfeed.com",
    ],
    "messaging": [
        "discord.com", "www.discord.com", "web.telegram.org",
    ],
}

# DNS-over-HTTPS providers that browsers use to bypass /etc/hosts.
# Blocking these forces Chrome/Firefox/etc back to system DNS.
DOH_BLOCK_DOMAINS = [
    "dns.google", "dns.google.com",
    "dns64.dns.google",
    "cloudflare-dns.com", "one.one.one.one",
    "mozilla.cloudflare-dns.com",
    "dns.quad9.net",
    "doh.opendns.com",
    "dns.nextdns.io",
    "doh.cleanbrowsing.org",
    "dns.adguard-dns.com",
    "doh.dns.sb",
    "dns.controld.com",
    "freedns.controld.com",
    "chrome.cloudflare-dns.com",
]

def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DAEMON
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LocalDNSProxy(threading.Thread):
    def __init__(self, ff_daemon):
        super().__init__(daemon=True)
        self.ff_daemon = ff_daemon
        self.sock = None
        self.active = True
        
        self.upstream_dns = "8.8.8.8"
        if self.ff_daemon.original_dns:
            for svc, dns_list in self.ff_daemon.original_dns.items():
                if dns_list and "aren't any" not in dns_list and dns_list.strip():
                    first = dns_list.strip().split()[0]
                    # Never forward to ourselves — would create infinite loop
                    if first and first not in ("127.0.0.1", "::1"):
                        self.upstream_dns = first
                        break

    def _bind_with_retry(self, max_attempts=10, initial_delay=1.0):
        """Retry binding to port 53 with exponential backoff for boot race."""
        delay = initial_delay
        for attempt in range(max_attempts):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind(("127.0.0.1", 53))
                logging.info("DNS Proxy bound to port 53 (attempt %d).", attempt + 1)
                return True
            except OSError as exc:
                logging.warning("DNS Proxy bind failed (attempt %d/%d): %s", 
                              attempt + 1, max_attempts, exc)
                if self.sock:
                    self.sock.close()
                time.sleep(delay)
                delay = min(delay * 2, 10.0)
        logging.error("DNS Proxy: exhausted all bind attempts.")
        return False

    def run(self):
        if not self._bind_with_retry():
            self.active = False
            return
            
        logging.info("DNS Proxy listening on 127.0.0.1:53")
        while self.active:
            try:
                r, _, _ = select.select([self.sock], [], [], 1.0)
                if not r:
                    continue
                data, addr = self.sock.recvfrom(4096)
                if not data:
                    continue
                self._handle_query(data, addr)
            except Exception as exc:
                logging.error("DNS Proxy loop error: %s", exc)

    def stop(self):
        self.active = False
        try:
            if self.sock:
                self.sock.close()
        except:
            pass

    def _extract_domain(self, data: bytes) -> str:
        parts = []
        idx = 12
        try:
            while idx < len(data) and data[idx] != 0:
                length = data[idx]
                parts.append(data[idx+1:idx+1+length].decode('utf-8'))
                idx += 1 + length
            return ".".join(parts).lower()
        except Exception:
            return ""

    def _make_nxdomain(self, query: bytes) -> bytes:
        try:
            hdr = struct.unpack("!HHHHHH", query[:12])
            flags = (hdr[1] | 0x8000) & 0xFE00
            flags = flags | 0x0080 | 3
            idx = 12
            while query[idx] != 0:
                idx += 1 + query[idx]
            idx += 5
            resp_hdr = struct.pack("!HHHHHH", hdr[0], flags, hdr[2], 0, 0, 0)
            return resp_hdr + query[12:idx]
        except Exception:
            return b''

    def _handle_query(self, data: bytes, addr):
        domain = self._extract_domain(data)
        if not domain:
            return
            
        allowed = False
        if domain == "localhost" or domain.endswith(".local"):
            allowed = True
        else:
            for d in self.ff_daemon.blocked_domains:
                if domain == d or domain.endswith("." + d):
                    allowed = True
                    break

        if allowed:
            try:
                fw = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                fw.settimeout(2.0)
                fw.sendto(data, (self.upstream_dns, 53))
                resp, _ = fw.recvfrom(4096)
                self.sock.sendto(resp, addr)
            except Exception:
                pass
        else:
            resp = self._make_nxdomain(data)
            if resp:
                self.sock.sendto(resp, addr)

class ForcedFocusDaemon:
    def __init__(self):
        self.active = False
        self.mode = "blacklist"
        self.blocked_domains: list[str] = []
        self.session_expiry: datetime | None = None
        self.pending_unlock_at: datetime | None = None
        self.hosts_hash: str | None = None
        self.dns_proxy = None
        self.original_dns: dict[str, str] = {}
        self.whitelist_resolved: dict[str, list[str]] = {}
        self.whitelist_count: int = 0
        self.total_duration_seconds: int = 0
        self.session_type: str = "standard"
        self.pomo_focus_minutes: int = 0
        self.pomo_break_minutes: int = 0
        self.pomo_total_cycles: int = 0
        self.pomo_current_cycle: int = 0
        self.pomo_phase: str = "focus"
        self.pomo_phase_expiry: datetime | None = None
        self.lock = threading.Lock()
        self._passphrase_attempts = 0
        self._last_attempt_time = 0.0
        # Monotonic time anchors (immune to clock manipulation)
        self._mono_session_end: float = 0.0
        self._mono_unlock_end: float = 0.0
        self._mono_pomo_phase_end: float = 0.0
        self._reenforce_flag = False  # Set by signal handler, handled by watchdog
        self.schedules: list = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self):
        setup_logging()
        logging.info("ForcedFocus daemon v2 starting (PID %d).", os.getpid())
        self._ensure_config_dir()
        self._ensure_lists_file()
        self._install_signal_handlers()
        # Restore session BEFORE starting watchdog to avoid race (C2)
        with self.lock:
            self._restore_session()

        wt = threading.Thread(target=self._watchdog_loop, name="watchdog", daemon=True)
        wt.start()
        
        ht = threading.Thread(target=self._http_server, name="http", daemon=True)
        ht.start()
        
        self._socket_server()

    @staticmethod
    def _ensure_config_dir():
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.chmod(str(CONFIG_DIR), 0o700)

    @staticmethod
    def _ensure_lists_file():
        if not LISTS_FILE.exists():
            LISTS_FILE.write_text(json.dumps({"blacklist": [], "whitelist": []}, indent=2))
            os.chmod(str(LISTS_FILE), 0o644)

    def _install_signal_handlers(self):
        def _handler(signum, _frame):
            name = signal.Signals(signum).name
            logging.warning("Caught %s — setting re-enforce flag.", name)
            # Non-blocking: just set flag, watchdog will re-enforce (C1 fix)
            self._reenforce_flag = True
        signal.signal(signal.SIGTERM, _handler)
        signal.signal(signal.SIGINT, _handler)
        signal.signal(signal.SIGHUP, _handler)

    # ── Lists Management ──────────────────────────────────────────────────────

    def _load_lists(self) -> dict:
        try:
            return json.loads(LISTS_FILE.read_text())
        except Exception:
            return {"blacklist": [], "whitelist": []}

    def _save_lists(self, lists: dict):
        LISTS_FILE.write_text(json.dumps(lists, indent=2))

    def _cmd_get_lists(self) -> dict:
        lists = self._load_lists()
        return {"status": "ok", "lists": lists}

    @staticmethod
    def _validate_domain(domain: str) -> bool:
        """Validate domain format: ASCII alphanumeric + hyphens + dots, reasonable length."""
        import re
        if not domain or len(domain) > 253:
            return False
        if any(c in domain for c in '\n\r\t \\/'):
            return False
        if '.' not in domain:
            return False
        if domain[0] in '.-' or domain[-1] in '.-':
            return False
        if not re.match(r'^[a-z0-9]([a-z0-9\-\.]*[a-z0-9])?$', domain):
            return False
        if '..' in domain:
            return False
        return True

    def _cmd_add_domain(self, cmd: dict) -> dict:
        with self.lock:
            if self.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if not self._validate_domain(domain):
            return {"status": "error", "message": "Invalid domain."}
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            lists = self._load_lists()
            if domain not in lists[list_name]:
                lists[list_name].append(domain)
                self._save_lists(lists)
            return {"status": "ok", "message": f"Added {domain} to {list_name}.", "lists": lists}

    def _cmd_add_domains(self, cmd: dict) -> dict:
        """Bulk-add multiple domains to a list."""
        with self.lock:
            if self.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
        list_name = cmd.get("list", "blacklist")
        domains = cmd.get("domains", [])
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            lists = self._load_lists()
            added = 0
            for d in domains:
                domain = d.strip().lower()
                if self._validate_domain(domain) and domain not in lists[list_name]:
                    lists[list_name].append(domain)
                    added += 1
            self._save_lists(lists)
            return {"status": "ok", "message": f"Added {added} domains to {list_name}.", "lists": lists}

    def _cmd_remove_domain(self, cmd: dict) -> dict:
        with self.lock:
            if self.active:
                return {"status": "error", "message": "Cannot modify lists during active session."}
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        with self.lock:
            lists = self._load_lists()
            if domain in lists[list_name]:
                lists[list_name].remove(domain)
                self._save_lists(lists)
            return {"status": "ok", "message": f"Removed {domain} from {list_name}.", "lists": lists}

    # ── Session Management ────────────────────────────────────────────────────

    def _restore_session(self):
        if not SESSION_LOCK.exists():
            logging.info("No persisted session found. Daemon idle.")
            return
        try:
            data = json.loads(SESSION_LOCK.read_text())
            expiry = datetime.fromisoformat(data["expiry"])
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logging.error("Corrupt session.lock (%s). Removing.", exc)
            SESSION_LOCK.unlink(missing_ok=True)
            return

        if datetime.now() >= expiry:
            logging.info("Persisted session expired. Cleaning up.")
            self.mode = data.get("mode", "blacklist")
            if self.mode == "whitelist":
                self.original_dns = data.get("original_dns", {})
            self._cleanup_session()
            return

        if data.get("schedules"):
            try:
                for sch in data["schedules"]:
                    sch_time = datetime.fromisoformat(sch["start_time"])
                    self.schedules.append({
                        "start_time": sch_time,
                        "end_time": datetime.fromisoformat(sch["end_time"]),
                        "cmd": sch["cmd"]
                    })
                self.schedules.sort(key=lambda x: x["start_time"])
                if not data.get("expiry"):
                    logging.info("Restored %d scheduled sessions.", len(self.schedules))
                    return
            except Exception as exc:
                logging.error("Failed to restore scheduled sessions: %s", exc)
                self.schedules = []

        if not data.get("expiry"):
            return

        wall_remaining = (expiry - datetime.now()).total_seconds()
        self.total_duration_seconds = data.get("duration_minutes", 120) * 60
        
        if "mono_elapsed" in data and "last_persist_wall" in data:
            wall_gap = (datetime.now() - datetime.fromisoformat(data["last_persist_wall"])).total_seconds()
            mono_remaining = self.total_duration_seconds - data["mono_elapsed"] - wall_gap
            remaining = min(wall_remaining, mono_remaining)
        else:
            remaining = wall_remaining
        remaining = max(0, remaining)

        self.mode = data.get("mode", "blacklist")
        self.session_expiry = expiry
        self.remaining_seconds = remaining
        self.session_type = data.get("session_type", "standard")
        self.pomo_focus_minutes = data.get("pomo_focus_minutes", 0)
        self.pomo_break_minutes = data.get("pomo_break_minutes", 0)
        self.pomo_total_cycles = data.get("pomo_total_cycles", 0)
        self.pomo_current_cycle = data.get("pomo_current_cycle", 0)
        self.pomo_phase = data.get("pomo_phase", "focus")
        
        now_mono = get_continuous_time()

        if data.get("pending_unlock_at"):
            self.pending_unlock_at = datetime.fromisoformat(data["pending_unlock_at"])
            unlock_remaining = max(0, (self.pending_unlock_at - datetime.now()).total_seconds())
            if unlock_remaining <= 0:
                logging.info("Pending unlock expired during downtime. Ending session.")
                if self.mode == "whitelist":
                    self.original_dns = data.get("original_dns", {})
                self._cleanup_session()
                return
            self._mono_unlock_end = now_mono + unlock_remaining
            self.pending_unlock_seconds = unlock_remaining
        else:
            self.pending_unlock_at = None
            self.pending_unlock_seconds = 0
            self._mono_unlock_end = 0.0

        if data.get("pomo_phase_expiry"):
            self.pomo_phase_expiry = datetime.fromisoformat(data["pomo_phase_expiry"])
            self.pomo_phase_remaining = max(0, (self.pomo_phase_expiry - datetime.now()).total_seconds())
        else:
            self.pomo_phase_expiry = None
            self.pomo_phase_remaining = 0

        # Set monotonic anchors from remaining wall-clock time
        self._mono_session_end = now_mono + remaining
        
        if self.pomo_phase_expiry:
            self._mono_pomo_phase_end = now_mono + max(0, (self.pomo_phase_expiry - datetime.now()).total_seconds())

        self.active = True
        
        if self.mode == "whitelist":
            self.original_dns = data.get("original_dns", {})
            self.blocked_domains = data.get("blocked_domains", [])
            self.whitelist_resolved = data.get("whitelist_resolved", {})
            self.whitelist_count = len(self.blocked_domains)
        else:
            self.blocked_domains = self._get_blacklist_domains()

        if self.session_type == "pomodoro" and self.pomo_phase_expiry:
            if datetime.now() >= self.pomo_phase_expiry:
                logging.info("Pomodoro phase expired during downtime. Advancing.")
                self._transition_pomodoro_phase()
                logging.info("Resuming %s session — %d min remaining.", self.mode, int(remaining / 60))
                return

        is_break = self.session_type == "pomodoro" and self.pomo_phase == "break"
        if self.mode == "whitelist":
            if not is_break:
                self._enforce_whitelist()
        else:
            if not is_break:
                self._enforce_block()
        logging.info("Resuming %s session — %d min remaining.", self.mode, int(remaining / 60))

    def _start_session(self, cmd: dict) -> dict:
        duration_minutes = cmd.get("duration_minutes", 120)
        mode = cmd.get("mode", "blacklist")
        # D3: Validate inputs before acquiring lock
        try:
            duration_minutes = int(duration_minutes)
        except (TypeError, ValueError):
            return {"status": "error", "message": "Invalid duration."}
        if duration_minutes < 1 or duration_minutes > 1440:
            return {"status": "error", "message": "Duration must be 1–1440 minutes."}
        if mode not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid mode."}
        with self.lock:
            # Parse scheduling arguments
            schedule_in = cmd.get("schedule_in_minutes")
            schedule_at = cmd.get("schedule_at_time")
            start_time = None
            if schedule_in:
                start_time = datetime.now() + timedelta(minutes=int(schedule_in))
            elif schedule_at:
                try:
                    now = datetime.now()
                    formats = [
                        "%Y-%m-%dT%H:%M",       # HTML5 datetime-local
                        "%Y-%m-%d %H:%M",       # CLI basic
                        "%Y-%m-%d %I:%M %p",    # CLI AM/PM
                        "%Y-%m-%d %I:%M%p",
                        "%I:%M %p",             # Just time AM/PM
                        "%I:%M%p",
                        "%H:%M",                # Just time 24h
                    ]
                    for fmt in formats:
                        try:
                            parsed = datetime.strptime(schedule_at.strip(), fmt)
                            if parsed.year == 1900:
                                start_time = now.replace(hour=parsed.hour, minute=parsed.minute, second=0, microsecond=0)
                                if start_time <= now:
                                    start_time += timedelta(days=1)
                            else:
                                start_time = parsed
                            break
                        except ValueError:
                            continue
                            
                    if not start_time:
                        return {"status": "error", "message": "Invalid date/time format. Use 'YYYY-MM-DD HH:MM AM/PM' or 'HH:MM AM/PM'."}
                        
                except Exception as exc:
                    return {"status": "error", "message": f"Failed to parse schedule time: {exc}"}

            duration_minutes = cmd.get("duration_minutes", 120)
            try:
                duration_minutes = int(duration_minutes)
            except ValueError:
                return {"status": "error", "message": "Duration must be an integer."}

            if duration_minutes <= 0:
                return {"status": "error", "message": "Duration must be > 0."}

            is_scheduling = start_time and start_time > datetime.now()
            
            # Check overlap if active
            if self.active:
                if not is_scheduling:
                    rem = (self.session_expiry - datetime.now()).total_seconds()
                    return {
                        "status": "already_active",
                        "message": f"Session active. {int(rem/60)}m {int(rem%60)}s remaining.",
                    }
                if start_time < self.session_expiry:
                    return {"status": "error", "message": f"Schedule overlaps with active session (ends at {self.session_expiry.strftime('%H:%M')})."}
                    
            if is_scheduling:
                end_time = start_time + timedelta(minutes=duration_minutes)
                
                # Check overlap with existing schedules
                for sch in self.schedules:
                    if max(start_time, sch["start_time"]) < min(end_time, sch["end_time"]):
                        return {"status": "error", "message": f"Schedule overlaps with an existing schedule (starts at {sch['start_time'].strftime('%m-%d %H:%M')})."}
                        
                sch_cmd = cmd.copy()
                sch_cmd.pop("schedule_in_minutes", None)
                sch_cmd.pop("schedule_at_time", None)
                
                self.schedules.append({
                    "start_time": start_time,
                    "end_time": end_time,
                    "cmd": sch_cmd
                })
                self.schedules.sort(key=lambda x: x["start_time"])
                self._persist_session_lock()
                
                logging.info("Session scheduled to start at %s.", start_time.strftime("%Y-%m-%d %I:%M %p"))
                return {
                    "status": "ok",
                    "message": f"Session scheduled to start at {start_time.strftime('%Y-%m-%d %I:%M %p')}.",
                    "scheduled": True,
                    "starts_at": start_time.strftime("%Y-%m-%d %I:%M %p")
                }

            self.mode = mode
            self.session_type = cmd.get("session_type", "standard")
            expiry = datetime.now() + timedelta(minutes=duration_minutes)
            self.session_expiry = expiry
            self.active = True
            self.total_duration_seconds = duration_minutes * 60
            self.pending_unlock_at = None
            # Monotonic anchors
            now_mono = get_continuous_time()
            self._mono_session_end = now_mono + (duration_minutes * 60)
            self._mono_unlock_end = 0.0

            # Extract pomodoro params from command
            if self.session_type == "pomodoro":
                self.pomo_focus_minutes = cmd.get("focus_minutes", 25)
                self.pomo_break_minutes = cmd.get("break_minutes", 5)
                self.pomo_total_cycles = cmd.get("cycles", 4)
                self.pomo_current_cycle = 1
                self.pomo_phase = "focus"
                self.pomo_phase_expiry = datetime.now() + timedelta(minutes=self.pomo_focus_minutes)
                self._mono_pomo_phase_end = now_mono + (self.pomo_focus_minutes * 60)

            session_data = {
                "started": datetime.now().isoformat(),
                "expiry": expiry.isoformat(),
                "mode": mode,
                "duration_minutes": duration_minutes,
                "session_type": self.session_type,
                "pomo_focus_minutes": self.pomo_focus_minutes,
                "pomo_break_minutes": self.pomo_break_minutes,
                "pomo_total_cycles": self.pomo_total_cycles,
                "pomo_current_cycle": self.pomo_current_cycle,
                "pomo_phase": self.pomo_phase,
                "pomo_phase_expiry": self.pomo_phase_expiry.isoformat() if self.pomo_phase_expiry else None,
                "mono_elapsed": 0.0,
                "last_persist_wall": datetime.now().isoformat(),
                "schedules": [
                    {
                        "start_time": sch["start_time"].isoformat(),
                        "end_time": sch["end_time"].isoformat(),
                        "cmd": sch["cmd"]
                    }
                    for sch in self.schedules
                ]
            }
            self.remaining_seconds = duration_minutes * 60
            self.pending_unlock_seconds = 0
            if self.session_type == "pomodoro":
                self.pomo_phase_remaining = self.pomo_focus_minutes * 60

            if mode == "whitelist":
                self.original_dns = self._get_current_dns_servers()
                wl_domains = self._load_lists().get("whitelist", [])
                self.blocked_domains = wl_domains  # Used by DNS proxy as allow-list
                session_data["blocked_domains"] = self.blocked_domains
                session_data["original_dns"] = self.original_dns
                SESSION_LOCK.write_text(json.dumps(session_data))
                self._enforce_whitelist()
                count = len(wl_domains)
                self.whitelist_count = count
                if self.session_type == "pomodoro":
                    msg = f"Pomodoro (Whitelist): {count} domains allowed for {self.pomo_total_cycles} cycles."
                else:
                    msg = f"Whitelist mode: {count} domains allowed for {duration_minutes} min."
            else:
                self.blocked_domains = self._get_blacklist_domains()
                SESSION_LOCK.write_text(json.dumps(session_data))
                self._enforce_block()
                count = len(self.blocked_domains)
                if self.session_type == "pomodoro":
                    msg = f"Pomodoro (Blacklist): {count} domains blocked for {self.pomo_total_cycles} cycles."
                else:
                    msg = f"Blacklist mode: {count} domains blocked for {duration_minutes} min."

            logging.info("Session started (%s) — expires %s.", mode, expiry.strftime("%H:%M:%S"))
            return {
                "status": "ok",
                "message": msg,
                "mode": mode,
                "domains_count": count,
                "expires_at": expiry.strftime("%H:%M:%S"),
            }

    def _request_stop(self, passphrase: str) -> dict:
        with self.lock:
            if not self.active:
                return {"status": "ok", "message": "No active session."}
            # Rate limit passphrase attempts
            now_mono = time.monotonic()
            if self._passphrase_attempts >= 5:
                cooldown = min(60, 2 ** (self._passphrase_attempts - 5))
                elapsed = now_mono - self._last_attempt_time
                if elapsed < cooldown:
                    wait = int(cooldown - elapsed)
                    logging.warning("Passphrase rate-limited. %ds remaining.", wait)
                    return {"status": "error", "message": f"Too many attempts. Wait {wait}s."}
            self._last_attempt_time = now_mono
            if not self._verify_passphrase(passphrase):
                self._passphrase_attempts += 1
                logging.warning("Invalid kill-switch passphrase attempt (#%d).", self._passphrase_attempts)
                return {"status": "error", "message": "Invalid passphrase."}
            # Reset rate limiter on success
            self._passphrase_attempts = 0
            if self.pending_unlock_at:
                now_mono = get_continuous_time()
                rem_mono = self._mono_unlock_end - now_mono
                if rem_mono > 0:
                    return {
                        "status": "pending",
                        "message": f"Unlock already pending. {int(rem_mono/60)}m {int(rem_mono%60)}s remaining.",
                    }
            self.pending_unlock_at = datetime.now() + timedelta(seconds=DELAYED_UNLOCK_S)
            self._mono_unlock_end = get_continuous_time() + DELAYED_UNLOCK_S
            self._persist_session_lock()
            unlock_str = self.pending_unlock_at.strftime("%H:%M:%S")
            logging.info("Delayed unlock requested — scheduled at %s.", unlock_str)
            return {
                "status": "pending",
                "message": f"Unlock request accepted. Releases at {unlock_str} (20-min delay).",
            }

    def _get_status(self) -> dict:
        with self.lock:
            schedules_res = []
            for sch in self.schedules:
                schedules_res.append({
                    "starts_at": sch["start_time"].strftime("%Y-%m-%d %I:%M %p"),
                    "starting_in_seconds": max(0, int((sch["start_time"] - datetime.now()).total_seconds())),
                    "mode": sch["cmd"].get("mode", "blacklist"),
                    "session_type": sch["cmd"].get("session_type", "standard"),
                    "duration_minutes": sch["cmd"].get("duration_minutes", 120),
                })
                
            if not self.active:
                return {
                    "status": "ok", 
                    "active": False, 
                    "state": "idle",
                    "mode": None, 
                    "message": "Idle.",
                    "schedules": schedules_res
                }
            
            # C3: Use monotonic time for all remaining-seconds fields
            now_mono = get_continuous_time()
            rem = int(max(0, self._mono_session_end - now_mono))
            result = {
                "status": "ok",
                "active": True,
                "mode": self.mode,
                "expires_at": self.session_expiry.strftime("%H:%M:%S"),
                "remaining_seconds": rem,
                "total_duration_seconds": self.total_duration_seconds,
                "domains_count": len(self.blocked_domains) if self.mode == "blacklist" else self.whitelist_count,
                "pending_unlock": self.pending_unlock_at.strftime("%H:%M:%S") if self.pending_unlock_at else None,
                "pending_unlock_seconds": int(max(0, self._mono_unlock_end - now_mono)) if self._mono_unlock_end > 0 else None,
                "session_type": self.session_type,
                "schedules": schedules_res
            }
            if self.session_type == "pomodoro":
                result["pomo_phase"] = self.pomo_phase
                result["pomo_current_cycle"] = self.pomo_current_cycle
                result["pomo_total_cycles"] = self.pomo_total_cycles
                result["pomo_focus_minutes"] = self.pomo_focus_minutes
                result["pomo_break_minutes"] = self.pomo_break_minutes
                if self._mono_pomo_phase_end > 0:
                    phase_rem = int(max(0, self._mono_pomo_phase_end - now_mono))
                    result["pomo_phase_remaining"] = phase_rem
                    result["pomo_phase_total"] = (self.pomo_focus_minutes if self.pomo_phase == "focus" else self.pomo_break_minutes) * 60
            return result

    # ── Blacklist Enforcement ─────────────────────────────────────────────────

    def _get_blacklist_domains(self) -> list[str]:
        lists = self._load_lists()
        bl = lists.get("blacklist", [])
        if bl:
            expanded = set()
            for d in bl:
                expanded.add(d)
                # Expand with common subdomain prefixes for broader /etc/hosts coverage
                for prefix in ["www.", "m.", "api.", "cdn.", "static.", "app.", "mail.", "login.", "accounts."]:
                    if not d.startswith(prefix):
                        expanded.add(prefix + d)
            return sorted(expanded)
        # Fallback to hard-coded default
        domains = []
        for sites in DEFAULT_BLOCKLIST.values():
            domains.extend(sites)
        return domains

    def _enforce_block(self):
        """Blacklist mode: inject 127.0.0.1 entries into /etc/hosts."""
        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            block = self._build_blacklist_block()
            content = content.rstrip("\n") + "\n\n" + block + "\n"
            HOSTS_PATH.write_text(content)
            subprocess.run(["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            self._flush_dns()
            self.hosts_hash = hashlib.sha256(content.encode()).hexdigest()
        except Exception as exc:
            logging.error("enforce_block failed: %s", exc)

    def _build_blacklist_block(self) -> str:
        lines = [MARKER_BEGIN, "# Mode: BLACKLIST", f"# Expires: {self.session_expiry.isoformat()}"]
        for domain in self.blocked_domains:
            lines.append(f"127.0.0.1\t{domain}")
            lines.append(f"::1\t\t{domain}")
        # Block DNS-over-HTTPS providers to prevent browser bypass
        lines.append("# DoH providers (anti-bypass)")
        for domain in DOH_BLOCK_DOMAINS:
            lines.append(f"127.0.0.1\t{domain}")
            lines.append(f"::1\t\t{domain}")
        lines.append(MARKER_END)
        return "\n".join(lines)

    # ── Whitelist Enforcement ─────────────────────────────────────────────────

    @staticmethod
    def _get_network_services() -> list[str]:
        """Get all network service names, including hardware-disabled ones.
        
        We include *-prefixed services because they can become active
        mid-session (e.g., plugging in Ethernet).
        """
        out = subprocess.run(
            ["networksetup", "-listallnetworkservices"],
            capture_output=True, text=True, timeout=5,
        )
        lines = out.stdout.strip().split("\n")
        # First line is always the header: "An asterisk (*) denotes..."
        services = []
        for line in lines[1:]:
            stripped = line.strip().lstrip("*").strip()
            if stripped:
                services.append(stripped)
        return services

    def _get_current_dns_servers(self) -> dict[str, str]:
        """Get current DNS servers for all network services."""
        result = {}
        try:
            services = self._get_network_services()
            for svc in services:
                dns_out = subprocess.run(
                    ["networksetup", "-getdnsservers", svc],
                    capture_output=True, text=True, timeout=5,
                )
                result[svc] = dns_out.stdout.strip()
        except Exception as exc:
            logging.error("Failed to get DNS servers: %s", exc)
        return result


    def _enforce_whitelist(self):
        """Whitelist mode: redirect DNS to local proxy + block DoH in /etc/hosts."""
        try:
            if not self.dns_proxy:
                self.dns_proxy = LocalDNSProxy(self)
                self.dns_proxy.start()
            self._set_dns_to_localhost()
            # M4: Block DoH providers in /etc/hosts for whitelist mode too
            self._enforce_doh_block()
            self._flush_dns()
            logging.info("Whitelist enforced via Local DNS Proxy.")
        except Exception as exc:
            logging.error("enforce_whitelist failed: %s", exc)

    def _enforce_doh_block(self):
        """Block DNS-over-HTTPS providers in /etc/hosts (whitelist anti-bypass)."""
        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            lines = [MARKER_BEGIN, "# Mode: WHITELIST (DoH block)",
                     f"# Expires: {self.session_expiry.isoformat()}"]
            lines.append("# DoH providers (anti-bypass)")
            for domain in DOH_BLOCK_DOMAINS:
                lines.append(f"127.0.0.1\t{domain}")
                lines.append(f"::1\t\t{domain}")
            lines.append(MARKER_END)
            block = "\n".join(lines)
            content = content.rstrip("\n") + "\n\n" + block + "\n"
            HOSTS_PATH.write_text(content)
            subprocess.run(["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
        except Exception as exc:
            logging.error("_enforce_doh_block failed: %s", exc)



    def _set_dns_to_localhost(self):
        """Redirect all network services' DNS to 127.0.0.1."""
        try:
            services = self._get_network_services()
            for svc in services:
                subprocess.run(
                    ["networksetup", "-setdnsservers", svc, "127.0.0.1"],
                    capture_output=True, timeout=5,
                )
            logging.info("DNS redirected to 127.0.0.1 for %d services.", len(services))
        except Exception as exc:
            logging.error("Failed to redirect DNS: %s", exc)

    def _restore_dns(self):
        """Restore original DNS servers from saved state."""
        if not self.original_dns:
            # If no saved DNS, set to "empty" (use DHCP defaults)
            try:
                services = self._get_network_services()
                for svc in services:
                    subprocess.run(["networksetup", "-setdnsservers", svc, "empty"], capture_output=True, timeout=5)
            except Exception as exc:
                logging.error("Failed to reset DNS: %s", exc)
            return

        for svc, dns_str in self.original_dns.items():
            try:
                if "There aren't any DNS Servers" in dns_str or not dns_str.strip():
                    subprocess.run(["networksetup", "-setdnsservers", svc, "empty"], capture_output=True, timeout=5)
                else:
                    servers = dns_str.strip().split("\n")
                    subprocess.run(["networksetup", "-setdnsservers", svc] + servers, capture_output=True, timeout=5)
            except Exception as exc:
                logging.error("Failed to restore DNS for %s: %s", svc, exc)
        logging.info("DNS servers restored.")

    # ── Common Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _strip_block(content: str) -> str:
        result = []
        inside = False
        for line in content.split("\n"):
            if MARKER_BEGIN in line:
                inside = True
                continue
            if MARKER_END in line:
                inside = False
                continue
            if not inside:
                result.append(line)
        while result and result[-1].strip() == "":
            result.pop()
        return "\n".join(result)

    def _enforce_current_mode(self):
        if self.mode == "whitelist":
            self._enforce_whitelist()
        else:
            self._enforce_block()

    def _remove_block(self):
        """Remove blocking from /etc/hosts without ending the session."""
        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            self.hosts_hash = None
            if self.mode == "whitelist":
                if self.dns_proxy:
                    self.dns_proxy.stop()
                    self.dns_proxy = None
                self._restore_dns()
            self._flush_dns()
        except Exception as exc:
            logging.error("_remove_block error: %s", exc)

    def _transition_pomodoro_phase(self):
        if self.pomo_phase == "focus":
            self.pomo_phase = "break"
            self.pomo_phase_remaining = self.pomo_break_minutes * 60
            self.pomo_phase_expiry = datetime.now() + timedelta(seconds=self.pomo_phase_remaining)
            self._mono_pomo_phase_end = get_continuous_time() + self.pomo_phase_remaining
            self._remove_block()
            self._persist_session_lock()
            logging.info("Pomodoro: cycle %d focus ended. Break for %dm.", 
                         self.pomo_current_cycle, self.pomo_break_minutes)
        else:
            self.pomo_current_cycle += 1
            if self.pomo_current_cycle > self.pomo_total_cycles:
                logging.info("Pomodoro: all %d cycles complete.", self.pomo_total_cycles)
                self._cleanup_session()
                return
            self.pomo_phase = "focus"
            self.pomo_phase_remaining = self.pomo_focus_minutes * 60
            self.pomo_phase_expiry = datetime.now() + timedelta(seconds=self.pomo_phase_remaining)
            self._mono_pomo_phase_end = get_continuous_time() + self.pomo_phase_remaining
            self._enforce_current_mode()
            self._persist_session_lock()
            logging.info("Pomodoro: cycle %d/%d focus started.", 
                         self.pomo_current_cycle, self.pomo_total_cycles)

    def _cleanup_session(self):
        logging.info("Cleaning up session (mode=%s)...", self.mode)
        was_whitelist = self.mode == "whitelist"

        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            if was_whitelist:
                if self.dns_proxy:
                    self.dns_proxy.stop()
                    self.dns_proxy = None
                self._restore_dns()
            self._flush_dns()
        except Exception as exc:
            logging.error("cleanup_session error: %s", exc)

        SESSION_LOCK.unlink(missing_ok=True)
        self.active = False
        self.hosts_hash = None
        self.session_expiry = None
        self.pending_unlock_at = None
        self.blocked_domains = []
        self.original_dns = {}
        self.whitelist_resolved = {}
        self.whitelist_count = 0
        self.total_duration_seconds = 0
        self.mode = "blacklist"
        self.session_type = "standard"
        self.pomo_focus_minutes = 0
        self.pomo_break_minutes = 0
        self.pomo_total_cycles = 0
        self.pomo_current_cycle = 0
        self.pomo_phase = "focus"
        self.pomo_phase_expiry = None
        self._mono_session_end = 0.0
        self._mono_unlock_end = 0.0
        self._mono_pomo_phase_end = 0.0
        self._passphrase_attempts = 0
        self._reenforce_flag = False
        # Do NOT clear schedules on session cleanup!
        logging.info("Session ended. Hosts restored. DNS flushed.")

    @staticmethod
    def _flush_dns():
        """Aggressive DNS flush — clears macOS cache and forces browsers to re-resolve."""
        subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=5)
        subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=5)
        # Full mDNSResponder reset (clears all cached records)
        subprocess.run(["killall", "-USR1", "mDNSResponder"], capture_output=True, timeout=5)

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def _persist_session_lock(self):
        """Re-create session.lock from in-memory state."""
        data = {
            "schedules": [
                {
                    "start_time": sch["start_time"].isoformat(),
                    "end_time": sch["end_time"].isoformat(),
                    "cmd": sch["cmd"]
                }
                for sch in self.schedules
            ]
        }
        if self.active and self.session_expiry:
            data.update({
                "started": (self.session_expiry - timedelta(seconds=self.total_duration_seconds)).isoformat(),
                "expiry": self.session_expiry.isoformat(),
                "duration_minutes": self.total_duration_seconds // 60,
                "mode": self.mode,
                "session_type": self.session_type,
                "mono_elapsed": get_continuous_time() - (self._mono_session_end - self.total_duration_seconds),
                "last_persist_wall": datetime.now().isoformat(),
            })
            if self.pending_unlock_at:
                data["pending_unlock_at"] = self.pending_unlock_at.isoformat()
                
            if self.session_type == "pomodoro":
                data.update({
                    "pomo_focus_minutes": self.pomo_focus_minutes,
                    "pomo_break_minutes": self.pomo_break_minutes,
                    "pomo_total_cycles": self.pomo_total_cycles,
                    "pomo_current_cycle": self.pomo_current_cycle,
                    "pomo_phase": self.pomo_phase,
                    "pomo_phase_expiry": self.pomo_phase_expiry.isoformat() if self.pomo_phase_expiry else None,
                })
            if self.mode == "whitelist":
                data["original_dns"] = self.original_dns
                data["whitelist_resolved"] = self.whitelist_resolved
                data["blocked_domains"] = self.blocked_domains
                
        try:
            SESSION_LOCK.write_text(json.dumps(data))
            logging.info("session.lock re-created from memory.")
        except Exception as exc:
            logging.error("Failed to persist session.lock: %s", exc)

    def _verify_dns_redirect(self):
        """Whitelist mode: verify DNS still points to 127.0.0.1, re-enforce if tampered."""
        try:
            services = self._get_network_services()
            for svc in services:
                dns_out = subprocess.run(
                    ["networksetup", "-getdnsservers", svc],
                    capture_output=True, text=True, timeout=5,
                )
                current_dns = dns_out.stdout.strip()
                if "127.0.0.1" not in current_dns and "aren't any" not in current_dns.lower():
                    logging.warning("DNS TAMPER on '%s': '%s' — re-enforcing.", svc, current_dns)
                    subprocess.run(
                        ["networksetup", "-setdnsservers", svc, "127.0.0.1"],
                        capture_output=True, timeout=5,
                    )
        except Exception as exc:
            logging.error("DNS verify error: %s", exc)

    def _watchdog_loop(self):
        logging.info("Watchdog thread started (interval=%.0fms).", WATCHDOG_INTERVAL * 1000)
        dns_check_counter = 0
        persist_counter = 0
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            cmd_to_start = None
            
            with self.lock:
                if getattr(self, "schedules", []):
                    # Check if the first schedule (sorted by start_time) is ready
                    if datetime.now() >= self.schedules[0]["start_time"]:
                        sch = self.schedules.pop(0)
                        cmd_to_start = sch["cmd"]
                        self._persist_session_lock()
                        if self.active:
                            self.active = False # Reset to allow fresh start

            if cmd_to_start:
                logging.info("Scheduled time reached. Automatically starting session.")
                self._start_session(cmd_to_start)
                continue

            with self.lock:
                if not self.active:
                    continue

                now_mono = get_continuous_time()
                
                persist_counter += 1
                if persist_counter >= 120:  # 120 * 250ms = 30s
                    persist_counter = 0
                    self._persist_session_lock()

                # C1: Handle signal-driven re-enforce (flag set without lock)
                if self._reenforce_flag:
                    self._reenforce_flag = False
                    if not (self.session_type == "pomodoro" and self.pomo_phase == "break"):
                        logging.info("Signal re-enforce: re-applying block rules.")
                        try:
                            self._enforce_current_mode()
                        except Exception as exc:
                            logging.error("Signal re-enforce failed: %s", exc)

                # Use monotonic time for duration checks (immune to clock changes)
                if now_mono >= self._mono_session_end:
                    logging.info("Session timer expired.")
                    self._cleanup_session()
                    continue
                if self._mono_unlock_end > 0 and now_mono >= self._mono_unlock_end:
                    logging.info("Delayed unlock period reached. Unlocking.")
                    self._cleanup_session()
                    continue

                # Pomodoro phase check
                if self.session_type == "pomodoro" and self._mono_pomo_phase_end > 0:
                    if now_mono >= self._mono_pomo_phase_end:
                        self._transition_pomodoro_phase()
                        continue

                # Skip integrity checks during pomodoro break
                if self.session_type == "pomodoro" and self.pomo_phase == "break":
                    continue

                # Integrity check: /etc/hosts (blacklist mode only)
                if self.mode != "whitelist":
                    try:
                        current = HOSTS_PATH.read_text()
                        h = hashlib.sha256(current.encode()).hexdigest()
                        if h != self.hosts_hash:
                            logging.warning("HOSTS TAMPER DETECTED. Re-enforcing.")
                            self._enforce_block()
                    except Exception as exc:
                        logging.error("Watchdog hosts error: %s", exc)

                # Integrity check: session.lock existence
                if not SESSION_LOCK.exists():
                    logging.warning("SESSION.LOCK DELETED. Re-creating from memory.")
                    self._persist_session_lock()
                    # Also re-enforce block since file was tampered
                    if self.mode == "whitelist":
                        self._enforce_whitelist()
                    else:
                        self._enforce_block()

                # Integrity check: DNS (whitelist mode, every ~2 seconds)
                if self.mode == "whitelist":
                    if self.dns_proxy and not self.dns_proxy.is_alive() and not (self.session_type == "pomodoro" and self.pomo_phase == "break"):
                        logging.warning("DNS Proxy thread died. Restarting.")
                        self.dns_proxy = LocalDNSProxy(self)
                        self.dns_proxy.start()
                        
                    dns_check_counter += 1
                    if dns_check_counter >= 8:  # 8 * 250ms = 2s
                        dns_check_counter = 0
                        self._verify_dns_redirect()

    # ── Passphrase ────────────────────────────────────────────────────────────

    @staticmethod
    def _verify_passphrase(passphrase: str) -> bool:
        if not KS_HASH_FILE.exists():
            return False
        try:
            stored = json.loads(KS_HASH_FILE.read_text())
            salt = bytes.fromhex(stored["salt"])
            expected = stored["hash"]
        except (json.JSONDecodeError, KeyError, ValueError):
            return False
        computed = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 100_000).hex()
        return hmac.compare_digest(computed, expected)

    # ── Socket Server ─────────────────────────────────────────────────────────

    def _socket_server(self):
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o600)
        
        user_file = Path("/etc/forcefocus/user")
        if user_file.exists():
            try:
                import pwd
                username = user_file.read_text().strip()
                uid = pwd.getpwnam(username).pw_uid
                os.chown(SOCK_PATH, uid, -1)
            except Exception as exc:
                logging.error("Failed to chown socket: %s", exc)

        sock.listen(5)
        sock.settimeout(SOCKET_TIMEOUT)
        logging.info("Command socket listening at %s.", SOCK_PATH)

        while True:
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError as exc:
                logging.error("Socket accept error: %s", exc)
                time.sleep(1)
                continue
            try:
                conn.settimeout(5.0)
                chunks = []
                while True:
                    chunk = conn.recv(8192)
                    if not chunk:
                        break
                    chunks.append(chunk)
                raw = b''.join(chunks).decode("utf-8").strip()
                if not raw:
                    continue
                response = self._dispatch_command(raw)
                conn.sendall(json.dumps(response).encode("utf-8"))
            except Exception as exc:
                logging.error("Socket handler error: %s", exc)
                try:
                    conn.sendall(json.dumps({"status": "error", "message": str(exc)}).encode("utf-8"))
                except Exception:
                    pass
            finally:
                conn.close()

    def _dispatch_command(self, raw: str) -> dict:
        try:
            cmd = json.loads(raw)
        except json.JSONDecodeError:
            return {"status": "error", "message": "Malformed JSON."}

        action = cmd.get("action", "")

        if action == "start":
            return self._start_session(cmd)
        elif action == "stop":
            return self._request_stop(cmd.get("key", ""))
        elif action == "status":
            return self._get_status()
        elif action == "get_lists":
            return self._cmd_get_lists()
        elif action == "add_domain":
            return self._cmd_add_domain(cmd)
        elif action == "add_domains":
            return self._cmd_add_domains(cmd)
        elif action == "remove_domain":
            return self._cmd_remove_domain(cmd)
        else:
            return {"status": "error", "message": f"Unknown action: {action}"}

    def _http_server(self):
        global WEB_DIR
        local_web = Path(__file__).parent / "web"
        if local_web.exists():
            WEB_DIR = local_web
        try:
            server = EmbeddedHTTPServer((WEB_HOST, WEB_PORT), EmbeddedWebHandler)
            server.daemon_ref = self
            logging.info("Web UI listening at http://%s:%d", WEB_HOST, WEB_PORT)
            server.serve_forever()
        except Exception as exc:
            logging.error("HTTP server failed: %s", exc)

class EmbeddedHTTPServer(HTTPServer):
    allow_reuse_address = True
    daemon_ref = None


class EmbeddedWebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _is_origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        if origin in ("http://localhost:7070", "http://127.0.0.1:7070"):
            return True
        if origin.startswith("chrome-extension://"):
            return True
        return False

    def _get_cors_origin(self) -> str:
        origin = self.headers.get("Origin")
        if origin and (origin in ("http://localhost:7070", "http://127.0.0.1:7070") or origin.startswith("chrome-extension://")):
            return origin
        return "http://127.0.0.1:7070"

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, filepath: Path):
        if not filepath.exists() or not filepath.is_file():
            self.send_error(404)
            return
        try:
            filepath.resolve().relative_to(WEB_DIR.resolve())
        except ValueError:
            self.send_error(403)
            return

        mime, _ = mimetypes.guess_type(str(filepath))
        if mime is None:
            mime = "application/octet-stream"

        body = filepath.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        MAX_BODY = 65536
        length = int(self.headers.get("Content-Length", 0))
        if length == 0 or length > MAX_BODY:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path.startswith("/api/") and not self._is_origin_allowed():
            self._send_json({"status": "error", "message": "CORS policy: Origin not allowed."}, 403)
            return

        if path == "/api/status":
            self._send_json(self.server.daemon_ref._get_status())
        elif path == "/api/lists":
            self._send_json(self.server.daemon_ref._cmd_get_lists())
        elif path == "/" or path == "":
            self._send_file(WEB_DIR / "index.html")
        else:
            self._send_file(WEB_DIR / path.lstrip("/"))

    def do_POST(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        
        if not self._is_origin_allowed():
            self._send_json({"status": "error", "message": "CORS policy: Origin not allowed."}, 403)
            return
            
        body = self._read_body()

        if path == "/api/start":
            cmd = {
                "action": "start",
                "duration_minutes": body.get("duration", 120),
                "mode": body.get("mode", "blacklist"),
                "session_type": body.get("session_type", "standard"),
                "focus_minutes": body.get("focus_minutes", 25),
                "break_minutes": body.get("break_minutes", 5),
                "cycles": body.get("cycles", 4),
            }
            if "schedule_in" in body:
                cmd["schedule_in_minutes"] = body["schedule_in"]
            if "schedule_at" in body:
                cmd["schedule_at_time"] = body["schedule_at"]
            self._send_json(self.server.daemon_ref._start_session(cmd))

        elif path == "/api/stop":
            self._send_json(self.server.daemon_ref._request_stop(body.get("key", "")))

        elif path.startswith("/api/lists/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4 and parts[3] == "bulk":
                cmd = {
                    "action": "add_domains",
                    "list": parts[2],
                    "domains": body.get("domains", []),
                }
                self._send_json(self.server.daemon_ref._cmd_add_domains(cmd))
            else:
                cmd = {
                    "action": "add_domain",
                    "list": parts[-1],
                    "domain": body.get("domain", ""),
                }
                self._send_json(self.server.daemon_ref._cmd_add_domain(cmd))
        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if not self._is_origin_allowed():
            self._send_json({"status": "error", "message": "CORS policy: Origin not allowed."}, 403)
            return

        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "lists":
            cmd = {
                "action": "remove_domain",
                "list": parts[2],
                "domain": "/".join(parts[3:]),
            }
            self._send_json(self.server.daemon_ref._cmd_remove_domain(cmd))
        else:
            self._send_json({"status": "error", "message": "Unknown endpoint."}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", self._get_cors_origin())
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


def main():
    if os.geteuid() != 0:
        print("ERROR: ForcedFocus daemon must run as root.", file=sys.stderr)
        sys.exit(1)
    daemon = ForcedFocusDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
