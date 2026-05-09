# ForcedFocus

ForcedFocus is an absolute productivity infrastructure designed to eliminate distractions and keep you focused.

## Components
- **CLI**: `forcefocus_cli.py` to interact with the daemon
- **Daemon**: `forcefocus_daemon.py` the background sentinel that enforces blocks
- **Web Interface**: `forcefocus_web.py` accessible at `http://localhost:7070`
- **Menubar**: `forcefocus_menubar.swift` for quick macOS access

## Installation

Run the install script with root privileges:
```bash
sudo bash install.sh
```

## Quick Start
- Dashboard: http://localhost:7070
- Check status: `forcefocus status`
- Start session: `forcefocus start`
- Stop session: `forcefocus stop`

## Contributing
Please see the `.github` directory for Issue and PR templates.
