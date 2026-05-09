💡 What: Extracted the inline object literal from `escapeHtml` inside `web/app.js` and `web/settings.js` into a constant map (`HTML_ESCAPE_MAP`) defined outside the function.
🎯 Why: In vanilla JavaScript UI code, declaring object literals inside a `.replace()` callback allocates new object memory for every matched character. By reusing a static map, we avoid unnecessary memory allocation overhead during frequent string manipulations.
📊 Impact: Reduces memory allocation operations inside `escapeHtml` string manipulation loops to zero for object allocations, allowing JavaScript engines to avoid garbage collection spikes when escaping a lot of text (e.g. rendering intents or tasks).
🔬 Measurement: Verify tests run properly, or profile UI with Chrome DevTools to observe less memory jitter and GC overhead when navigating around the app.

Resolves the issue related to Bolt performance optimization.
