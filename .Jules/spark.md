## 2026-05-08 - [CSS Animations] 
Learning: Reusing `display: none` toggles for CSS animations. 
Action: When a class toggles `display: none` (like `.hidden`), we can use `@keyframes` directly on the element instead of `transition`, as `display` isn't animatable via `transition` but `animation` will run upon the element being rendered.
