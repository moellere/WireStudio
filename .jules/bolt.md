## 2024-05-18 - Single-Pass Collection Building
**Learning:** Chained array methods like `.filter().map()` inside `useMemo` still allocate intermediate arrays in JavaScript, causing unnecessary garbage collection overhead when building Sets or Maps.
**Action:** Use single-pass `for...of` loops when building Sets or Maps from arrays to avoid intermediate allocations.

## 2024-07-27 - O(N) Lookups in Render Loops
**Learning:** Using `.find()` to lookup values in an array from inside a `.map()` or a `for` loop executing during rendering creates an O(N^2) time complexity bottleneck. In `buildModel` (WiringView.tsx), looking up a bus type by its ID via `.find()` across all components and connections repeatedly scanned the `buses` array.
**Action:** Pre-compute lookup maps (e.g., `Map<id, value>`) before loops to achieve O(1) lookups during heavy data processing or rendering.

## 2024-05-18 - Single-Pass Lookup Building in `useMemo`
**Learning:** We often chain `.map()` to build an array of IDs and then loop again to build a dictionary mapping IDs to labels in `useMemo` hooks. This causes multiple iterations and intermediate array allocations.
**Action:** When building both an array of IDs and a dictionary map from the same source data, use a single `for...of` loop to populate both simultaneously.
