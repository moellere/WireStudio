## 2024-05-18 - Single-Pass Collection Building
**Learning:** Chained array methods like `.filter().map()` inside `useMemo` still allocate intermediate arrays in JavaScript, causing unnecessary garbage collection overhead when building Sets or Maps.
**Action:** Use single-pass `for...of` loops when building Sets or Maps from arrays to avoid intermediate allocations.
