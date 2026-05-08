🧪 Testing Improvement for `_start_session` in `forcefocus_daemon.py`

🎯 **What:** The `_start_session` method in `forcefocus_daemon.py` had missing test coverage for its input validation and error handling logic.

📊 **Coverage:** Three new test cases were added to `tests/test_forcefocus_daemon.py`:
- `test_start_session_invalid_duration_type`: Verifies that invalid string/type inputs for duration correctly return an error message.
- `test_start_session_invalid_duration_range`: Verifies that duration boundaries (< 1 or > 1440 minutes) are checked and return proper error messages.
- `test_start_session_invalid_mode`: Verifies that invalid session modes correctly return an error.

✨ **Result:** Test coverage is improved, specifically ensuring that user inputs for Pomodoro/blacklist sessions are validated accurately and return predictable error states.
