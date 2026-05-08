🧪 Testing improvement for `forcefocus_daemon.py`

🎯 **What:** The testing gap addressed
- Addressed testing gap for `_persist_session_lock` in `forcefocus_daemon.py`.
- Tested the error handling logic, confirming it correctly calls `logging.error` and correctly catches exceptions when `_atomic_write_json` fails.

📊 **Coverage:** What scenarios are now tested
- Tested `_persist_session_lock` standard successful serialization, verifying that `_atomic_write_json` is called with correctly structured data (`schedules` and `session_expiry`).
- Tested `_persist_session_lock` error handling by mocking `_atomic_write_json` to raise an `Exception`, verifying that `logging.error` is called and the exception is caught correctly.

✨ **Result:** The improvement in test coverage
- The error handling in `_persist_session_lock` is now completely tested and verified.

