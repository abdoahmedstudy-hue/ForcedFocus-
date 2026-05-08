🧪 Testing Improvement: Add coverage for `_enforce_block` error handling

🎯 **What:**
The `_enforce_block` method in `forcefocus_daemon.py` performs complex operations including invoking `chflags` via `subprocess.run` and several other file I/O operations. Previously, its error handling (non-zero `chflags` exit codes and generic exceptions during file writing) was completely untested, leaving a coverage gap for these edge cases.

📊 **Coverage:**
Two new tests have been added to `tests/test_forcefocus_daemon.py`:
- `test_enforce_block_chflags_error`: Mocks `subprocess.run` to return an exit code `1` and simulate permission errors. It verifies that `logging.warning` is correctly called twice (once for `nouchg` and once for `uchg`), and crucially, verifies that the process still successfully proceeds with subsequent configuration logic (`write_text`, `_enforce_firewall`, `_clear_browser_caches`, etc.) instead of crashing early.
- `test_enforce_block_exception`: Mocks a generic catastrophic exception during `Path.read_text` to verify the generic `except Exception:` block properly catches the error and reports it via `logging.error` without completely panicking the daemon loop.

✨ **Result:**
By adding these tests, we guarantee the reliability of the `_enforce_block` operation against environmental inconsistencies, ensuring failures during system configuration are strictly logged and handled seamlessly without impacting core functionality.
