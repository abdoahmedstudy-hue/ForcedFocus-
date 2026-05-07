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
import hashlib
import logging
import threading
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

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

class ForcedFocusDaemon:
    def __init__(self):
        self.active = False
        self.mode = "blacklist"
        self.blocked_domains: list[str] = []
        self.session_expiry: datetime | None = None
        self.pending_unlock_at: datetime | None = None
        self.hosts_hash: str | None = None
        self.original_dns: dict[str, str] = {}
        self.whitelist_resolved: dict[str, list[str]] = {}
        self.whitelist_count: int = 0
        self.total_duration_seconds: int = 0
        self.lock = threading.Lock()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def run(self):
        setup_logging()
        logging.info("ForcedFocus daemon v2 starting (PID %d).", os.getpid())
        self._ensure_config_dir()
        self._ensure_lists_file()
        self._install_signal_handlers()
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
            logging.warning("Caught %s — re-enforcing block.", name)
            with self.lock:
                if self.active:
                    if self.mode == "whitelist":
                        try:
                            data = json.loads(SESSION_LOCK.read_text())
                            self._enforce_whitelist(data.get("whitelist_resolved", {}))
                        except Exception as exc:
                            logging.error("Whitelist re-enforce failed: %s", exc)
                    else:
                        self._enforce_block()
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

    def _cmd_add_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if not domain:
            return {"status": "error", "message": "No domain specified."}
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

        lists = self._load_lists()
        if domain not in lists[list_name]:
            lists[list_name].append(domain)
            self._save_lists(lists)
        return {"status": "ok", "message": f"Added {domain} to {list_name}.", "lists": lists}

    def _cmd_remove_domain(self, cmd: dict) -> dict:
        list_name = cmd.get("list", "blacklist")
        domain = cmd.get("domain", "").strip().lower()
        if list_name not in ("blacklist", "whitelist"):
            return {"status": "error", "message": "Invalid list name."}

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
        self.total_duration_seconds = data.get("duration_minutes", 120) * 60
        self.active = True
        if self.mode == "whitelist":
            self.original_dns = data.get("original_dns", {})
            self.whitelist_resolved = data.get("whitelist_resolved", {})
            self.whitelist_count = len(self.whitelist_resolved)
            self._enforce_whitelist_from_session(data)
        else:
            self.blocked_domains = self._get_blacklist_domains()
            self._enforce_block()
        logging.info("Resuming %s session — %d min remaining.", self.mode, int(remaining / 60))

    def _start_session(self, duration_minutes: int, mode: str = "blacklist") -> dict:
        with self.lock:
            if self.active:
                rem = (self.session_expiry - datetime.now()).total_seconds()
                return {
                    "status": "already_active",
                    "message": f"Session active. {int(rem/60)}m {int(rem%60)}s remaining.",
                }

            self.mode = mode
            expiry = datetime.now() + timedelta(minutes=duration_minutes)
            session_data = {
                "started": datetime.now().isoformat(),
                "expiry": expiry.isoformat(),
                "duration_minutes": duration_minutes,
                "mode": mode,
            }

            self.session_expiry = expiry
            self.pending_unlock_at = None
            self.active = True
            self.total_duration_seconds = duration_minutes * 60

            if mode == "whitelist":
                self.original_dns = self._get_current_dns_servers()
                session_data["original_dns"] = self.original_dns
                wl_domains = self._load_lists().get("whitelist", [])
                resolved = self._resolve_whitelist_domains(wl_domains)
                session_data["whitelist_resolved"] = resolved
                SESSION_LOCK.write_text(json.dumps(session_data))
                self._enforce_whitelist(resolved)
                self.whitelist_resolved = resolved
                count = len(wl_domains)
                self.whitelist_count = count
                msg = f"Whitelist mode: {count} domains allowed for {duration_minutes} min."
            else:
                self.blocked_domains = self._get_blacklist_domains()
                SESSION_LOCK.write_text(json.dumps(session_data))
                self._enforce_block()
                count = len(self.blocked_domains)
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
            if not self._verify_passphrase(passphrase):
                logging.warning("Invalid kill-switch passphrase attempt.")
                return {"status": "error", "message": "Invalid passphrase."}
            if self.pending_unlock_at:
                rem = (self.pending_unlock_at - datetime.now()).total_seconds()
                if rem > 0:
                    return {
                        "status": "pending",
                        "message": f"Unlock already pending. {int(rem/60)}m {int(rem%60)}s remaining.",
                    }
            self.pending_unlock_at = datetime.now() + timedelta(seconds=DELAYED_UNLOCK_S)
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
            rem = max(0, (self.session_expiry - datetime.now()).total_seconds())
            return {
                "status": "ok",
                "active": True,
                "mode": self.mode,
                "expires_at": self.session_expiry.strftime("%H:%M:%S"),
                "remaining_seconds": int(rem),
                "total_duration_seconds": self.total_duration_seconds,
                "domains_count": len(self.blocked_domains) if self.mode == "blacklist" else self.whitelist_count,
                "pending_unlock": self.pending_unlock_at.strftime("%H:%M:%S") if self.pending_unlock_at else None,
                "pending_unlock_seconds": max(0, int((self.pending_unlock_at - datetime.now()).total_seconds())) if self.pending_unlock_at else None,
            }

    # ── Blacklist Enforcement ─────────────────────────────────────────────────

    def _get_blacklist_domains(self) -> list[str]:
        lists = self._load_lists()
        bl = lists.get("blacklist", [])
        if bl:
            # Expand with www. variants
            expanded = set()
            for d in bl:
                expanded.add(d)
                if not d.startswith("www."):
                    expanded.add("www." + d)
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
        """Get active network service names, skipping the header line."""
        out = subprocess.run(
            ["networksetup", "-listallnetworkservices"],
            capture_output=True, text=True, timeout=5,
        )
        lines = out.stdout.strip().split("\n")
        # First line is always the header: "An asterisk (*) denotes..."
        # Skip it, then filter disabled services (marked with *)
        services = []
        for line in lines[1:]:
            stripped = line.strip()
            if stripped and not stripped.startswith("*"):
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

    def _resolve_whitelist_domains(self, domains: list[str]) -> dict[str, list[str]]:
        """Resolve whitelisted domains to IP addresses."""
        resolved = {}
        for base_domain in domains:
            for prefix in WHITELIST_PREFIXES:
                fqdn = prefix + base_domain
                try:
                    infos = socket.getaddrinfo(fqdn, 443, socket.AF_INET)
                    ips = list(set(info[4][0] for info in infos))
                    if ips:
                        resolved[fqdn] = ips
                except (socket.gaierror, OSError):
                    pass
        # Always allow localhost
        resolved["localhost"] = ["127.0.0.1"]
        return resolved

    def _enforce_whitelist(self, resolved: dict[str, list[str]]):
        """Whitelist mode: redirect DNS + pin allowed IPs in hosts."""
        try:
            # 1. Inject whitelisted IPs into /etc/hosts
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            block = self._build_whitelist_block(resolved)
            content = content.rstrip("\n") + "\n\n" + block + "\n"
            HOSTS_PATH.write_text(content)
            subprocess.run(["chflags", "uchg", str(HOSTS_PATH)], capture_output=True, timeout=5)

            # 2. Redirect all DNS to 127.0.0.1 (kills all non-hosts resolution)
            self._set_dns_to_localhost()

            # 3. Flush DNS
            self._flush_dns()
            self.hosts_hash = hashlib.sha256(content.encode()).hexdigest()
            logging.info("Whitelist enforced: %d domains pinned, DNS redirected.", len(resolved))
        except Exception as exc:
            logging.error("enforce_whitelist failed: %s", exc)

    def _enforce_whitelist_from_session(self, data: dict):
        """Re-enforce whitelist from persisted session data."""
        resolved = data.get("whitelist_resolved", {})
        self._enforce_whitelist(resolved)

    def _build_whitelist_block(self, resolved: dict[str, list[str]]) -> str:
        lines = [MARKER_BEGIN, "# Mode: WHITELIST", f"# Expires: {self.session_expiry.isoformat()}"]
        for fqdn, ips in sorted(resolved.items()):
            for ip in ips:
                lines.append(f"{ip}\t{fqdn}")
        lines.append(MARKER_END)
        return "\n".join(lines)

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

    def _cleanup_session(self):
        logging.info("Cleaning up session (mode=%s)...", self.mode)
        was_whitelist = self.mode == "whitelist"

        try:
            subprocess.run(["chflags", "nouchg", str(HOSTS_PATH)], capture_output=True, timeout=5)
            content = self._strip_block(HOSTS_PATH.read_text())
            HOSTS_PATH.write_text(content)
            if was_whitelist:
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
        logging.info("Session ended. Hosts restored. DNS flushed.")

    @staticmethod
    def _flush_dns():
        """Aggressive DNS flush — clears macOS cache and forces browsers to re-resolve."""
        # Standard macOS flush
        subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=5)
        subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=5)
        # Full mDNSResponder reset (clears all cached records)
        subprocess.run(["killall", "-USR1", "mDNSResponder"], capture_output=True, timeout=5)
        # Brief delay then flush again to catch any race conditions
        time.sleep(0.5)
        subprocess.run(["dscacheutil", "-flushcache"], capture_output=True, timeout=5)
        subprocess.run(["killall", "-HUP", "mDNSResponder"], capture_output=True, timeout=5)

    # ── Watchdog ──────────────────────────────────────────────────────────────

    def _persist_session_lock(self):
        """Re-create session.lock from in-memory state."""
        data = {
            "started": (self.session_expiry - timedelta(seconds=self.total_duration_seconds)).isoformat(),
            "expiry": self.session_expiry.isoformat(),
            "duration_minutes": self.total_duration_seconds // 60,
            "mode": self.mode,
        }
        if self.mode == "whitelist":
            data["original_dns"] = self.original_dns
            data["whitelist_resolved"] = self.whitelist_resolved
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
                now = datetime.now()
                if now >= self.session_expiry:
                    logging.info("Session timer expired.")
                    self._cleanup_session()
                    continue
                if self.pending_unlock_at and now >= self.pending_unlock_at:
                    logging.info("Delayed unlock period reached. Unlocking.")
                    self._cleanup_session()
                    continue

                # Integrity check: /etc/hosts
                try:
                    current = HOSTS_PATH.read_text()
                    h = hashlib.sha256(current.encode()).hexdigest()
                    if h != self.hosts_hash:
                        logging.warning("HOSTS TAMPER DETECTED. Re-enforcing.")
                        if self.mode == "whitelist":
                            data = json.loads(SESSION_LOCK.read_text())
                            self._enforce_whitelist(data.get("whitelist_resolved", {}))
                        else:
                            self._enforce_block()
                except Exception as exc:
                    logging.error("Watchdog hosts error: %s", exc)

                # Integrity check: session.lock existence
                if not SESSION_LOCK.exists():
                    logging.warning("SESSION.LOCK DELETED. Re-creating from memory.")
                    self._persist_session_lock()
                    # Also re-enforce block since file was tampered
                    if self.mode == "whitelist":
                        self._enforce_whitelist(self.whitelist_resolved)
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
        return computed == expected

    # ── Socket Server ─────────────────────────────────────────────────────────

    def _socket_server(self):
        if os.path.exists(SOCK_PATH):
            os.unlink(SOCK_PATH)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(SOCK_PATH)
        os.chmod(SOCK_PATH, 0o666)
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
                raw = conn.recv(8192).decode("utf-8").strip()
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
            duration = cmd.get("duration_minutes", 120)
            mode = cmd.get("mode", "blacklist")
            return self._start_session(int(duration), mode)
        elif action == "stop":
            return self._request_stop(cmd.get("key", ""))
        elif action == "status":
            return self._get_status()
        elif action == "get_lists":
            return self._cmd_get_lists()
        elif action == "add_domain":
            return self._cmd_add_domain(cmd)
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
