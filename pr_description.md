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
