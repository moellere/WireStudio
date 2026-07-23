## 2025-07-05 - Avoid inline filter logic in Inspector components
**Learning:** In highly-interactive, deep component trees like `Inspector.tsx` (which renders on component parameter or connection changes), placing `.filter()` or `.map()` directly inside the JSX return or an IIFE causes a new array allocation every render. This defeats downstream memoization (e.g. `CompatibilityList`) and increases garbage collection pressure.
**Action:** When extracting derived arrays from global context (`compatibilityWarnings`) to match a specific `inst.id`, always extract the logic to a `useMemo` at the top level of the component (above early returns). Safely handle `undefined` contexts within the hook.

## 2025-07-06 - Avoid sorting and O(N) grouping in unmemoized component closures
**Learning:** In interactive components like `AddComponentControl`, placing array `.push()` groupings into dictionaries and `.sort()` operations directly in the render body creates new objects and arrays on every keystroke or local state change (e.g. `setPicked`), severely impacting performance in lists.
**Action:** Always wrap grouping (e.g., `byCategory` dictionaries) and sorting (e.g., `categories.sort()`) of mostly-static library data inside a `useMemo` hook to avoid O(N) allocation and re-sorting during local state interactions.

## 2025-07-23 - Single-pass loops over chained array methods
**Learning:** Chaining `.filter().map()` or similar methods on large arrays (like `libraryComponents`) allocates multiple intermediate arrays. Even when wrapped in `useMemo`, this creates unnecessary garbage collection pressure when the dependencies change.
**Action:** When deriving Collections (like `Set`, `Map`, or simply returning a flattened/filtered Array) from large data structures, prefer a single-pass `for...of` loop instead of chained array methods to avoid intermediate allocations.
