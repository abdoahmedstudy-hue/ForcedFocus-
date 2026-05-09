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
from pathlib import Path
from datetime import datetime, timedelta

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
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 53))
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

    def run(self):
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

        remaining = (expiry - datetime.now()).total_seconds()
        self.mode = data.get("mode", "blacklist")
        self.session_expiry = expiry
        self.remaining_seconds = max(0, remaining)
        self.pending_unlock_seconds = max(0, (self.pending_unlock_at - datetime.now()).total_seconds()) if self.pending_unlock_at else 0
        self.total_duration_seconds = data.get("duration_minutes", 120) * 60
        self.session_type = data.get("session_type", "standard")
        self.pomo_focus_minutes = data.get("pomo_focus_minutes", 0)
        self.pomo_break_minutes = data.get("pomo_break_minutes", 0)
        self.pomo_total_cycles = data.get("pomo_total_cycles", 0)
        self.pomo_current_cycle = data.get("pomo_current_cycle", 0)
        self.pomo_phase = data.get("pomo_phase", "focus")
        if data.get("pomo_phase_expiry"):
            self.pomo_phase_expiry = datetime.fromisoformat(data["pomo_phase_expiry"])
            self.pomo_phase_remaining = max(0, (self.pomo_phase_expiry - datetime.now()).total_seconds())
        else:
            self.pomo_phase_expiry = None
            self.pomo_phase_remaining = 0

        # Set monotonic anchors from remaining wall-clock time
        now_mono = get_continuous_time()
        self._mono_session_end = now_mono + max(0, remaining)
        self._mono_unlock_end = 0.0
        if self.pomo_phase_expiry:
            self._mono_pomo_phase_end = now_mono + max(0, (self.pomo_phase_expiry - datetime.now()).total_seconds())

        self.active = True
        is_break = self.session_type == "pomodoro" and self.pomo_phase == "break"
        if self.mode == "whitelist":
            self.original_dns = data.get("original_dns", {})
            self.blocked_domains = data.get("blocked_domains", [])
            self.whitelist_resolved = data.get("whitelist_resolved", {})
            self.whitelist_count = len(self.blocked_domains)
            if not is_break:
                self._enforce_whitelist()
        else:
            self.blocked_domains = self._get_blacklist_domains()
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
            if self.active:
                rem = (self.session_expiry - datetime.now()).total_seconds()
                return {
                    "status": "already_active",
                    "message": f"Session active. {int(rem/60)}m {int(rem%60)}s remaining.",
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
            unlock_str = self.pending_unlock_at.strftime("%H:%M:%S")
            logging.info("Delayed unlock requested — scheduled at %s.", unlock_str)
            return {
                "status": "pending",
                "message": f"Unlock request accepted. Releases at {unlock_str} (20-min delay).",
            }

    def _get_status(self) -> dict:
        with self.lock:
            if not self.active:
                return {"status": "ok", "active": False, "mode": None, "message": "Idle."}
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
            "started": (self.session_expiry - timedelta(seconds=self.total_duration_seconds)).isoformat(),
            "expiry": self.session_expiry.isoformat(),
            "duration_minutes": self.total_duration_seconds // 60,
            "mode": self.mode,
            "session_type": self.session_type,
        }
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
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            with self.lock:
                if not self.active:
                    continue
                now_mono = get_continuous_time()

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


def main():
    if os.geteuid() != 0:
        print("ERROR: ForcedFocus daemon must run as root.", file=sys.stderr)
        sys.exit(1)
    daemon = ForcedFocusDaemon()
    daemon.run()

if __name__ == "__main__":
    main()
