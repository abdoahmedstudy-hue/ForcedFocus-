# ForcedFocus — Complete Architecture & Developer Guide

## 1. System Overview & Program Logic

**ForcedFocus** is an unbreakable, root-level website blocker for macOS designed to maximize productivity. It employs a multi-layered approach to enforce blocking both at the system network level and the browser level, making it highly resistant to tampering, bypasses, or circumvention by the user during active sessions.

### Core Features
*   **Blacklist Mode**: Blocks a specific list of domains while allowing the rest of the internet.
*   **Whitelist Mode**: Blocks the entire internet, allowing *only* a specific list of domains.
*   **Session Types**: Standard timer-based blocking and Pomodoro cycles (focus/break intervals).
*   **Delayed Unlock (Kill-Switch)**: Sessions cannot be stopped instantly. Requesting an unlock requires a pre-set passphrase and enforces a mandatory 20-minute delay before the block is lifted, discouraging impulsive quits.
*   **Anti-Tamper Mechanisms**: Uses monotonic clocks to prevent system time-travel attacks, enforces immutable flags on system files, and runs a high-frequency watchdog thread to detect and revert unauthorized changes.

### How the Blocking Works
1.  **System Level (Blacklist)**: Injects entries into `/private/etc/hosts` pointing blocked domains (and known DNS-over-HTTPS providers) to `127.0.0.1`. It then locks the file using the `uchg` (user immutable) flag and flushes the macOS DNS cache (`dscacheutil` and `mDNSResponder`). Subdomains are handled by hardcoding common prefixes (e.g., `www.`, `api.`).
2.  **System Level (Whitelist)**: Uses `networksetup` to re-route all active network interfaces' DNS servers to `127.0.0.1`. The daemon spins up a local UDP DNS Proxy on port 53. This proxy intercepts all DNS requests, returning `NXDOMAIN` for everything except the whitelisted domains (which are allowed dynamically using suffix matching). **Crucially**, it also modifies and locks `/private/etc/hosts` to block known DoH providers, ensuring the proxy isn't bypassed.
3.  **Browser Level (Chrome Extension)**: A companion Chrome extension uses the `declarativeNetRequest` API to enforce blocking directly within the browser, redirecting requests to a local `blocked.html` page. Note: In whitelist mode, the extension's logic currently contains a loophole for outbound links (via `excludedInitiatorDomains`), making the system-level DNS proxy the true ultimate enforcer.

---

## 2. Component Architecture

The system is composed of four main components interacting with each other:

1.  **The Daemon (`forcefocus_daemon.py`)**: Runs persistently as `root` via `launchd`. It holds the source of truth for the session state, manages system files, runs the DNS proxy, operates the watchdog loop, and embeds its own internal HTTP server.
2.  **The Legacy Web Server (`forcefocus_web.py`)**: A standalone script that serves the Web UI. While originally the primary web server communicating via Unix socket, this architecture is now legacy. The modern daemon uses an embedded direct-memory HTTP server (`EmbeddedHTTPServer`), making `forcefocus_web.py` redundant except for local development.
3.  **The Command Line Interface (`forcefocus_cli.py`)**: A terminal utility allowing users to start, stop, and query the status of the daemon via the Unix socket (`/var/run/forcefocus.sock`).
4.  **The Chrome Extension**: Polls the Web Server's API for the current state and dynamically updates Chrome's blocking rules to match the daemon's state.

---

## 3. Detailed File Breakdown

Here is a comprehensive breakdown of every file in the project, its function, how it works, and how to modify it.

### Core System Files

#### 1. `forcefocus_daemon.py`
*   **Function**: The core brain of the application.
*   **Logic**: 
    *   **Initialization**: Sets up logging, signal handlers, and restores any active session from `/etc/forcefocus/session.lock`.
    *   **Watchdog Loop**: Runs every 250ms. Checks if the session has expired, verifies `/etc/hosts` integrity via SHA256 hashing, ensures the DNS proxy is alive (if in whitelist mode), and verifies `networksetup` DNS settings haven't been tampered with.
    *   **LocalDNSProxy**: A module-level thread class that binds to UDP port 53. Parses incoming DNS binary packets, checks the domain against the allowed list, and either forwards the packet or synthesizes an `NXDOMAIN` response.
    *   **Socket & HTTP Servers**: Runs a Unix socket server to receive commands, and embeds an HTTP server to serve the web UI and API.
*   **How to modify**: When modifying state transitions (like Pomodoro phases), ensure `_persist_session_lock` is called. If changing blocking logic, update `_enforce_block` and `_enforce_whitelist`.

#### 2. `forcefocus_cli.py`
*   **Function**: Command-line wrapper for interacting with the daemon.
*   **Logic**: Uses `argparse` to parse commands (`start`, `stop`, `status`, `set-key`, `web`). For session management, it connects to the Unix socket (`/var/run/forcefocus.sock`) and exchanges JSON payloads. Note: The `set-key` command bypasses the socket entirely, writing the hashed passphrase directly to the filesystem at `/etc/forcefocus/ks_hash`.
*   **How to modify**: To add a new CLI command, create a function (e.g., `cmd_new`), add an argument parser in `build_parser()`, map it to the function, and ensure the daemon's `_dispatch_command` is updated to handle the new action.

#### 3. `forcefocus_web.py`
*   **Function**: A legacy standalone bridge and static file server.
*   **Logic**: Subclasses `BaseHTTPRequestHandler` to serve static files and forward API calls to the daemon via the Unix socket (`/var/run/forcefocus.sock`). 
    *   **Important Note**: The production daemon uses an identical but distinct internal class (`EmbeddedHTTPServer`) which bypasses the Unix socket to call methods directly. `forcefocus_web.py` is only used when started manually via the CLI for development.
*   **How to modify**: If modifying API logic, remember to update both this file (for dev) and the `EmbeddedWebHandler` inside `forcefocus_daemon.py` (for production).

#### 4. `com.forcefocus.daemon.plist`
*   **Function**: The macOS `launchd` configuration file.
*   **Logic**: Instructs macOS to run `forcefocus_daemon.py` as `root` at boot (`RunAtLoad`), restart it if it crashes (`KeepAlive`), and defines separate standard out (`/var/log/forcefocus.log`) and standard error (`/var/log/forcefocus_error.log`) log paths.
*   **How to modify**: Edit XML to change execution priority, environment variables, or log paths. Must run `sudo launchctl unload` and `load` for changes to take effect.

#### 5. `forcefocus.newsyslog.conf`
*   **Function**: macOS log rotation configuration.
*   **Logic**: Ensures `/var/log/forcefocus*.log` files do not grow infinitely. Keeps 5 historical archives of max 1024 KB each.
*   **How to modify**: Change the size `1024` or count `5` to adjust log retention.

### Installation & Uninstallation

#### 6. `install.sh`
*   **Function**: Deploys the system.
*   **Logic**: Validates root access, finds Python 3, creates `/etc/forcefocus`, copies Python scripts to `/usr/local/bin`, installs the web files, prompts the user to set a kill-switch passphrase, backs up `/etc/hosts`, and loads the LaunchDaemon.
*   **How to modify**: If adding new dependencies or files, add copy (`cp`) commands here and update file permissions (`chmod`/`chown root:wheel`).

#### 7. `uninstall.sh`
*   **Function**: Safely removes the system and legacy artifacts.
*   **Logic**: **Crucially**, it asks for the kill-switch passphrase before uninstalling to prevent unauthorized bypasses. However, because it immediately kills the daemon upon a successful passphrase entry, `uninstall.sh` acts as an **instant backdoor** to bypass the mandatory 20-minute unlock delay. It then unloads the legacy web LaunchAgents, restores DHCP DNS settings, and uses an inline Python script to cleanly strip ForcedFocus markers from `/etc/hosts` (despite a comment falsely claiming it uses `sed`).
*   **How to modify**: Ensure any new files added in `install.sh` are explicitly removed here.

### Web UI Frontend (`web/`)

#### 8. `web/index.html`
*   **Function**: The main dashboard UI.
*   **Logic**: Contains the HTML structure for the countdown timer (SVG ring), mode toggles, Pomodoro settings, list management (Blacklist/Whitelist textareas), and the unlock modal.
*   **How to modify**: Add new UI sections here. Use specific IDs for JavaScript interaction.

#### 9. `web/styles.css`
*   **Function**: Styling for the Web UI.
*   **Logic**: Uses a modern "Dark Glassmorphism" aesthetic with CSS variables for colors, static gradient background orbs, and responsive grid layouts.
*   **How to modify**: Update CSS variables at the `:root` to change the color scheme. 

#### 10. `web/app.js`
*   **Function**: Client-side logic for the Web UI.
*   **Logic**: 
    *   Polls `/api/status` every 2 seconds to keep the UI in sync with the daemon.
    *   Calculates and renders the SVG timer ring progress.
    *   Handles button clicks, formats API requests, and updates the DOM based on active/idle states.
*   **How to modify**: If adding a new feature, add event listeners in `initEvents()`, create API fetch wrappers, and update `refreshStatus()` or `setActiveUI()` to reflect new states.

### Chrome Extension (`chrome-extension/`)

#### 11. `manifest.json`
*   **Function**: Extension configuration (Manifest V3).
*   **Logic**: Declares permissions: `alarms` (for background polling), `declarativeNetRequest` (for blocking), `declarativeNetRequestFeedback`, and host permissions for `http://127.0.0.1:7070/*`. **Critically**, it also declares `blocked.html` under `web_accessible_resources`, which is structurally required for Chrome to permit the extension to redirect blocked sites. Sets up the background service worker and popup UI.
*   **How to modify**: Increment `"version"` when updating. Add new permissions here if needed.

#### 12. `background.js`
*   **Function**: Service worker that actively enforces blocking in the browser.
*   **Logic**: 
    *   Uses `chrome.alarms` to poll the local daemon API every ~3 seconds. (Note: Manifest V3 limits alarms to 1-minute intervals in packed production extensions; 3-second polling only functions in Developer Mode).
    *   **Blacklist**: Generates `declarativeNetRequest` rules redirecting blacklisted domains to `blocked.html`.
    *   **Whitelist**: Creates a catch-all rule blocking everything, with exception rules for whitelisted domains, `localhost`, and `127.0.0.1` (to ensure the Web UI remains accessible).
    *   *Architectural Loophole*: The whitelist's catch-all rule uses `excludedInitiatorDomains: ['127.0.0.1', 'localhost', ...allowedDomains]`. This means if a user clicks a link on an allowed site, the rule is bypassed, allowing navigation to blocked sites. Thus, the extension relies heavily on the system DNS proxy as a fallback.
*   **How to modify**: Chrome limits the number of dynamic rules; ensure `applyBlockRules()` handles list sizes efficiently.

#### 13. `popup.html` & `popup.css` & `popup.js`
*   **Function**: The mini-UI that appears when clicking the extension icon.
*   **Logic**: A condensed version of `web/app.js` and `index.html`. It allows starting standard or Pomodoro sessions and requesting unlocks directly from the browser popup. Checks `checkServer()` on load to show an offline message if the daemon isn't running.
*   **How to modify**: Similar to the main web app; update HTML for layout, CSS for styles, and JS for API interaction and state rendering.

#### 14. `blocked.html`
*   **Function**: The landing page shown when a site is blocked.
*   **Logic**: A visually appealing, static HTML page that parses the URL query parameter `?domain=...` via inline JS to tell the user which site was blocked.
*   **How to modify**: Update the inline CSS or HTML to change the messaging or aesthetics of the block page.

---

## 4. Deep Dive: System Anti-Tamper Logic

ForcedFocus is designed to be "unbreakable." Here is how it achieves this:

1.  **Monotonic Clocks**: Instead of using `datetime.now()` for session duration, the daemon uses `time.clock_gettime(time.CLOCK_MONOTONIC_RAW)`. This represents hardware uptime. If a user changes their Mac's system clock (e.g., fast-forwards 2 hours), `datetime.now()` is fooled, but the monotonic clock is not, preventing time-travel bypasses.
2.  **State Persistence (`session.lock`)**: State is written to `/etc/forcefocus/session.lock` upon state transitions (start, stop, or Pomodoro phase changes), as well as periodically every 30 seconds by the watchdog to sync elapsed monotonic time. Note: The current write mechanism (`pathlib.Path.write_text`) is not POSIX atomic and could result in corruption if the daemon crashes mid-write. If the daemon is force-killed (via `sudo kill -9`), `launchd` immediately restarts it. Upon boot, it reads `session.lock` and instantly re-applies the `/etc/hosts` and DNS restrictions.
3.  **File Immutability**: After writing to `/etc/hosts`, the daemon runs `chflags uchg /private/etc/hosts`. This prevents even the `root` user from editing the file manually without first removing the flag, adding a layer of friction.
4.  **Signal Handling**: If a user tries to send a graceful termination signal (`SIGTERM`, `SIGINT`), the daemon catches it, logs it, and sets a `_reenforce_flag`. The watchdog loop sees this flag and instantly re-applies the block rules instead of shutting down.
5.  **DNS Proxying**: Whitelist mode is notoriously difficult on macOS because browsers cache DNS aggressively. By spinning up a local proxy and redirecting the OS to query `127.0.0.1`, ForcedFocus gains absolute, packet-level control over DNS resolution, synthesizing fake responses for non-whitelisted sites.

## 5. Development Workflow

To make changes to the application:

1. **Daemon/CLI Changes**: 
   * Edit `forcefocus_daemon.py` or `forcefocus_cli.py`.
   * Restart the daemon: `sudo launchctl unload /Library/LaunchDaemons/com.forcefocus.daemon.plist` followed by `sudo launchctl load -w /Library/LaunchDaemons/com.forcefocus.daemon.plist`.
   * Check logs: `tail -f /var/log/forcefocus_error.log`.
2. **Web UI Changes**:
   * Edit files in `web/`.
   * Since the daemon serves these files directly from `/usr/local/share/forcefocus/web`, you must copy your local changes to that directory: `sudo cp -R web/* /usr/local/share/forcefocus/web/`, or run the standalone `forcefocus_web.py` for local dev.
3. **Extension Changes**:
   * Edit files in `chrome-extension/`.
   * Go to `chrome://extensions`, enable "Developer mode", click the refresh icon on the ForcedFocus extension.

This guide provides a total breakdown of ForcedFocus, its architecture, and operational logic.
