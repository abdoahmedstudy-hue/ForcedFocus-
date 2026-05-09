🧪 Testing Improvement: Add coverage for `_enforce_block` error handling

🎯 **What:**
The `_enforce_block` method in `forcefocus_daemon.py` performs complex operations including invoking `chflags` via `subprocess.run` and several other file I/O operations. Previously, its error handling (non-zero `chflags` exit codes and generic exceptions during file writing) was completely untested, leaving a coverage gap for these edge cases.

📊 **Coverage:**
Two new tests have been added to `tests/test_forcefocus_daemon.py`:
- `test_enforce_block_chflags_error`: Mocks `subprocess.run` to return an exit code `1` and simulate permission errors. It verifies that `logging.warning` is correctly called twice (once for `nouchg` and once for `uchg`), and crucially, verifies that the process still successfully proceeds with subsequent configuration logic (`write_text`, `_enforce_firewall`, `_clear_browser_caches`, etc.) instead of crashing early.
- `test_enforce_block_exception`: Mocks a generic catastrophic exception during `Path.read_text` to verify the generic `except Exception:` block properly catches the error and reports it via `logging.error` without completely panicking the daemon loop.

✨ **Result:**
By adding these tests, we guarantee the reliability of the `_enforce_block` operation against environmental inconsistencies, ensuring failures during system configuration are strictly logged and handled seamlessly without impacting core functionality.
## Title: "🧪 Add comprehensive test suite for CLI send_command"

## Description
🎯 **What:** The testing gap addressed
The `send_command` function in `forcefocus_cli.py` lacked test coverage, despite being the critical bridge between the CLI and the daemon via Unix sockets. It handles socket connections, serialization, and error scenarios.

📊 **Coverage:** What scenarios are now tested
Tests have been added in `tests/test_forcefocus_cli.py` under the new `TestSendCommand` class. Covered scenarios include:
- `test_daemon_not_found`: Triggered when the socket file is missing.
- `test_connection_refused`: Caught `ConnectionRefusedError` from socket connection.
- `test_timeout`: Caught `socket.timeout` during connection or receive.
- `test_socket_error`: General unhandled `Exception` occurring during socket communication.
- `test_empty_response`: Daemon accepts the connection but returns an empty payload.
- `test_success`: Valid JSON command is sent, the daemon processes it, and returns a correct JSON response.

✨ **Result:** The improvement in test coverage
The CLI's core communication mechanism is now verified, ensuring failures and successful transmissions are handled properly without side effects. Changes to IPC protocols or socket configurations will now be caught dynamically by the test suite, making future refactoring safer. All 47 tests pass.
🧪 Testing improvement for `forcefocus_daemon.py`

🎯 **What:** The testing gap addressed
- Addressed testing gap for `_persist_session_lock` in `forcefocus_daemon.py`.
- Tested the error handling logic, confirming it correctly calls `logging.error` and correctly catches exceptions when `_atomic_write_json` fails.

📊 **Coverage:** What scenarios are now tested
- Tested `_persist_session_lock` standard successful serialization, verifying that `_atomic_write_json` is called with correctly structured data (`schedules` and `session_expiry`).
- Tested `_persist_session_lock` error handling by mocking `_atomic_write_json` to raise an `Exception`, verifying that `logging.error` is called and the exception is caught correctly.

✨ **Result:** The improvement in test coverage
- The error handling in `_persist_session_lock` is now completely tested and verified.

🧪 Testing Improvement for `_start_session` in `forcefocus_daemon.py`

🎯 **What:** The `_start_session` method in `forcefocus_daemon.py` had missing test coverage for its input validation and error handling logic.

📊 **Coverage:** Three new test cases were added to `tests/test_forcefocus_daemon.py`:
- `test_start_session_invalid_duration_type`: Verifies that invalid string/type inputs for duration correctly return an error message.
- `test_start_session_invalid_duration_range`: Verifies that duration boundaries (< 1 or > 1440 minutes) are checked and return proper error messages.
- `test_start_session_invalid_mode`: Verifies that invalid session modes correctly return an error.

✨ **Result:** Test coverage is improved, specifically ensuring that user inputs for Pomodoro/blacklist sessions are validated accurately and return predictable error states.

🧪 Add tests for forcefocus_cli.cmd_web

🎯 **What:** The `cmd_web` function in `forcefocus_cli.py` lacked unit tests.

📊 **Coverage:** The new `TestForceFocusCLICmdWeb` class tests:
* Starting the web interface when the primary script exists in `/usr/local/bin`
* Starting the web interface when the primary script is missing, falling back to the directory containing the CLI script
* Providing a helpful error message when the web script isn't found anywhere
* Stopping the web interface and correctly handling the `stop` action

✨ **Result:** Enhanced test coverage ensures that CLI commands to start/stop the web interface are thoroughly tested and verified.
