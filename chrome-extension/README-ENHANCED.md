# ForcedFocus Chrome Extension (Enhanced Version)

This enhanced version of the ForcedFocus Chrome Extension provides advanced website blocking capabilities with additional features for better productivity and user experience.

## Features

### Core Blocking
- **Declarative Net Request API**: Uses Chrome's powerful blocking API for efficient domain blocking
- **Blacklist Mode**: Block specific websites and their subdomains
- **Whitelist Mode**: Allow only specified websites while blocking everything else
- **Rescue Mode**: Emergency lockdown blocking all websites

### Advanced Features
- **Analytics Dashboard**: Track blocked and allowed requests with statistics
- **Better Error Handling**: Intelligent retry mechanisms for API connections
- **Enhanced UI**: Improved popup interface with better visual design
- **Content Script Injection**: Enhanced blocked page experience
- **Background Sync**: More efficient polling and state management

### Session Management
- **Pomodoro Technique**: Built-in Pomodoro timer with focus/break cycles
- **Flexible Timing**: Custom durations and scheduling options
- **Secure Unlock**: Delayed unlock with passphrase protection
- **Real-time Updates**: Live timer and status updates

## Installation

1. Clone or download this repository
2. Open Chrome and navigate to `chrome://extensions`
3. Enable "Developer mode"
4. Click "Load unpacked" and select the extension directory
5. Ensure the ForcedFocus daemon is running on your Mac

## Architecture

```
background-enhanced.js     # Enhanced background service worker with analytics
popup-enhanced.js          # Improved popup UI with analytics
content.js                 # Content script for blocked page enhancements
blocked-enhanced.html      # Enhanced blocked page with better UX
manifest-enhanced.json     # Updated manifest with additional permissions
```

## Permissions

- `alarms`: For periodic background sync
- `declarativeNetRequest`: Core blocking functionality
- `browsingData`: Cache clearing for better blocking
- `storage`: Analytics data persistence
- `notifications`: Future notification support

## API Integration

The extension communicates with the ForcedFocus daemon via HTTP REST API:
- `GET /api/status`: Current session status
- `POST /api/start`: Start a new session
- `POST /api/stop`: Request session unlock
- `GET /api/lists`: Retrieve domain lists

## Development

```bash
# Load the extension in Chrome
# 1. Open chrome://extensions
# 2. Enable Developer Mode
# 3. Click "Load Unpacked"
# 4. Select this directory
```

## Analytics Features

- Blocked request counter
- Allowed request counter
- Session duration tracking
- Domain-specific blocking statistics

## Content Security

- All communication happens over localhost
- Passphrases are never stored in plain text
- Secure messaging between components
- Privacy-focused design

## Compatibility

- Chrome 88+
- Requires macOS ForcedFocus daemon
- Works with all major websites
- Compatible with other Chrome extensions

## License

ForcedFocus is distributed under the MIT License. See LICENSE file for details.