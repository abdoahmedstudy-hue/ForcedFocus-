
## 2026-05-18 - LocalDNSProxy active_domains_set Filtering
**Learning:** Checking subdomains against an allowed list inside a busy network hook (like the DNS proxy loop) with `.endswith()` iterating through an array (`for d in active_domains: if domain == d or domain.endswith("." + d)`) can create unnecessary performance overhead (O(n)). For thousands of blocked/allowed domains, this loop is run for *every* DNS query.
**Action:** Use a `set()` to cache active domains, and construct string segment lookups `parts = domain.split('.')`, validating subdomains backwards in O(m) operations where m is the number of sub-components (typically 2 to 4), completely bypassing the O(n) array scan and dropping query latency drastically.

## 2024-05-09 - Avoid inline objects in String.prototype.replace callbacks
**Learning:** For vanilla JavaScript UI performance, declaring inline object literals within frequently called callback functions (e.g., in `String.prototype.replace`) allocates new object memory on every match.
**Action:** Extract static mapping objects (like HTML character escapes) outside the function scope to reuse the same memory reference and prevent unnecessary allocations.
