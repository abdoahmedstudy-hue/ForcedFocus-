## 2024-05-08 - UI Race Conditions and Double Submit Learning
Learning: Without button locks (`disabled=true`) and AbortControllers on repeating API polls, fast clicking causes concurrent `POST/DELETE` duplicate requests leading to ghost errors, and slow network polling causes `GET` race conditions where old data overwrites new state.
Action: Always use `AbortController` for polling queries, and `disabled` states for mutation buttons to enforce single-flight concurrency.
## 2026-05-08 - System Integrity and Concurrency
Learning: Long-running threads like watchdogs can die from unhandled exceptions or state panics, locking the system entirely. Blocking local sockets indefinitely causes slowloris-style denial of service. Open, unauthenticated HTTP endpoints on localhost expose secrets to all users on multi-tenant environments.
Action: Implement monitor threads for critical system watchdogs to self-heal. Wrap local IPC sockets with concurrency limits (`threading.Thread` with bounded tracking). Use strict file permissions (0600) instead of unauthenticated HTTP endpoints for secrets like API tokens, and inject them cleanly into UI entry points via URL parameters.
