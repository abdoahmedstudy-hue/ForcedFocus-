🌊 Flow: Reliability fix - AbortControllers and Button Disabling

💡 What:
- Implemented `AbortController` functionality inside the `api` utility across `app.js`, `menubar.js`, and `settings.js`.
- Disabled UI mutation buttons (`btnStart`, `btnConfirmStop`, `addDomain`, `removeBtn`, `btnUnlockConfirm`, `saveSettings`, `saveGroup`, etc.) when their corresponding requests are pending.
- Fixed a minor bug with `raw.split` missing an escape character when adding new domains.
- Fixed a test asserting an older version of the chrome-extension UUID, updating it to the current UUID (`hcgpgflhkpdccdjkkobofpaemcgjmhdc`).

🎯 Why:
- Fast clicking would previously cause concurrent POST/DELETE duplicate requests, leading to ghost errors.
- Polling for GET requests without `AbortController` over slow networks risked older requests overwriting new states and caused overlapping race conditions.

🛡️ Resilience:
- Single-flight concurrency is now strongly enforced.
- Re-triggering API calls is explicitly blocked through UI `disabled=true` attributes while async calls to the backend resolve.
- Active polling requests are aborted gracefully avoiding data clashing when refreshing component states.

🧪 Testing:
- Verified syntax dynamically using node format evaluators.
- All 41 daemon Python tests passed, ensuring the mocked origin header reflects the correct extension namespace.
