🎯 **What:** Created missing tests for `forcefocus_web.py` to bridge the gap in testing coverage.
📊 **Coverage:** Now tests daemon socket communications (including error and retry cases), `ForcedFocusHandler` CORS logic `_is_origin_allowed` and `_get_cors_origin`, and endpoints for `/api/status`, `/api/start`, `/api/lists/blacklist/bulk`, and list DELETE.
✨ **Result:** Improved robustness by asserting that web server gracefully routes REST commands effectively into correct inter-process socket messages. All tests pass locally.
