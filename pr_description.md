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
