## 2024-05-18 - Single-Pass Collection Building
**Learning:** Chained array methods like `.filter().map()` inside `useMemo` still allocate intermediate arrays in JavaScript, causing unnecessary garbage collection overhead when building Sets or Maps.
**Action:** Use single-pass `for...of` loops when building Sets or Maps from arrays to avoid intermediate allocations.

## 2024-07-27 - O(N) Lookups in Render Loops
**Learning:** Using `.find()` to lookup values in an array from inside a `.map()` or a `for` loop executing during rendering creates an O(N^2) time complexity bottleneck. In `buildModel` (WiringView.tsx), looking up a bus type by its ID via `.find()` across all components and connections repeatedly scanned the `buses` array.
**Action:** Pre-compute lookup maps (e.g., `Map<id, value>`) before loops to achieve O(1) lookups during heavy data processing or rendering.

## 2024-05-18 - Single-Pass Lookup Building in `useMemo`
**Learning:** We often chain `.map()` to build an array of IDs and then loop again to build a dictionary mapping IDs to labels in `useMemo` hooks. This causes multiple iterations and intermediate array allocations.
**Action:** When building both an array of IDs and a dictionary map from the same source data, use a single `for...of` loop to populate both simultaneously.

## 2024-08-01 - Avoid new Set(arr.map()) for performance
**Learning:** Constructing a Set by mapping an array via `new Set(arr.map(fn))` causes an unnecessary intermediate array allocation in memory before the Set is built. This can create garbage collection overhead in render loops or frequently called utilities.
**Action:** Replace `new Set(arr.map(fn))` with a single-pass `for...of` loop to add items to a Set, avoiding the intermediate array entirely.

## 2024-08-01 - Avoid allocating full objects to extract scalar IDs
**Learning:** Helper functions like `readComponents(d)` allocate a full new object for every item in the array to provide a sanitized/normalized view. When a function only needs to extract primitive fields (like string `id`s for a Set or array), invoking these helpers wastes memory on object creation.
**Action:** When extracting scalar fields from raw JSON-like structures (e.g. `d.components`), iterate directly over the raw array instead of calling normalizing helper functions, checking types manually to satisfy TypeScript.
## 2024-05-18 - Avoid array iteration with .includes on small arrays
**Learning:** Using `.includes()` on an array inside tight loops or data transformations adds unnecessary O(N) array traversals per iteration.
**Action:** Inside tight loops, replace `.includes()` on small static arrays with direct strict inequality comparisons (e.g., `key !== 'a' && key !== 'b'`).
