## 2024-05-08 - UI Race Conditions and Double Submit Learning
Learning: Without button locks (`disabled=true`) and AbortControllers on repeating API polls, fast clicking causes concurrent `POST/DELETE` duplicate requests leading to ghost errors, and slow network polling causes `GET` race conditions where old data overwrites new state.
Action: Always use `AbortController` for polling queries, and `disabled` states for mutation buttons to enforce single-flight concurrency.
