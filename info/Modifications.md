# ForcedFocus Modifications — Scheduling Feature

This document records the architectural and file-level modifications made to integrate the unbreakable session scheduling feature ("Now", "Later", "Time").

## System-Level Logic Additions
1. **Unbreakable Scheduling**: The system now supports delayed activation of blocking sessions. Once a session is scheduled, it cannot be canceled.
2. **Daemon Resilience**: Scheduled sessions are persisted to the `session.lock` file to survive daemon crashes or system restarts.
3. **Watchdog Automation**: The daemon's internal watchdog automatically checks the clock and activates the block exactly at the scheduled time.

## File Modifications

### 1. `forcefocus_daemon.py`
*   **State Additions**: Added `is_scheduled` (boolean), `scheduled_start_time` (datetime), and `scheduled_cmd` (dict) to the `ForcedFocusDaemon` state to hold pending session info.
*   **Session Start (`_start_session`)**: Modified to parse `schedule_in_minutes` and `schedule_at_time` from the incoming API command. Enhanced the date parser to support multiple time formats, including AM/PM and specific dates (e.g., `YYYY-MM-DD HH:MM AM/PM`). If a schedule is detected, the daemon writes the scheduled state to `session.lock` and enters an active but non-blocking "scheduled" mode.
*   **Session Restore (`_restore_session`)**: Updated to handle the restoration of a scheduled state upon daemon reboot. If the scheduled time has passed during downtime, it automatically triggers the block upon restoration.
*   **Watchdog Loop (`_watchdog_loop`)**: Updated to evaluate the monotonic/wall clock against the `scheduled_start_time`. When the time hits, it automatically triggers `_start_session(scheduled_cmd)` without requiring user interaction.
*   **Status Reporting (`_get_status`)**: Added a `"state": "scheduled"` return alongside countdown logic (`starting_in_seconds`).
*   **Embedded Web Server (`EmbeddedWebHandler`)**: Forwarded schedule parameters (`schedule_in`, `schedule_at`) inside the `POST /api/start` route.

### 2. `forcefocus_cli.py`
*   **Arguments**: Added `--schedule-in MINUTES` and `--schedule-at 'YYYY-MM-DD HH:MM AM/PM'` optional arguments to the `start` command via `argparse`, explicitly supporting AM/PM and dates.
*   **Payload Construction**: Included the schedule parameters in the JSON payload sent to the daemon over the Unix socket.
*   **Status Readout**: Modified `cmd_status` to cleanly format and output scheduled session information (Starts At, Starting In) when the daemon is in the `scheduled` state, utilizing an AM/PM 12-hour format string.

### 3. `forcefocus_web.py`
*   **API Forwarding**: Updated the legacy standalone server's `POST /api/start` route to properly forward `schedule_in` and `schedule_at` fields to the daemon's Unix socket.

### 4. `web/index.html`
*   **UI Components**: Inserted a new "Schedule" UI Card containing:
    *   A three-way toggle switch ("Now", "Later", "Time").
    *   Dynamic, hidden-by-default input fields for minutes (`<input type="number">`) and specific dates/times (`<input type="datetime-local">`), standardizing the UI with the OS's native date and AM/PM time picker.

### 5. `web/app.js`
*   **DOM Selection**: Added the new scheduling UI elements to the `els` tracking object.
*   **Event Listeners**: Added click handlers to the schedule toggle buttons to show/hide the appropriate input fields.
*   **Payload Handling**: Updated the `btnStart` click handler to inject `schedule_in` or `schedule_at` into the `/api/start` payload based on the selected mode.
*   **State UI Rendering (`setActiveUI`)**: Added logic to handle the new `status.state === 'scheduled'` response. When scheduled, the UI changes the timer label to "STARTING IN", shows the countdown, and disables the progress ring animation until the session becomes actively enforced.

### 6. `web/styles.css`
*   **Styling**: Added a `.schedule-inputs` CSS block to match the existing "Dark Glassmorphism" aesthetics for the new input wrappers, standardizing the gap spacing and typography with the duration selectors.
