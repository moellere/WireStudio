## 2025-07-05 - Avoid inline filter logic in Inspector components
**Learning:** In highly-interactive, deep component trees like `Inspector.tsx` (which renders on component parameter or connection changes), placing `.filter()` or `.map()` directly inside the JSX return or an IIFE causes a new array allocation every render. This defeats downstream memoization (e.g. `CompatibilityList`) and increases garbage collection pressure.
**Action:** When extracting derived arrays from global context (`compatibilityWarnings`) to match a specific `inst.id`, always extract the logic to a `useMemo` at the top level of the component (above early returns). Safely handle `undefined` contexts within the hook.

## 2025-07-06 - Avoid sorting and O(N) grouping in unmemoized component closures
**Learning:** In interactive components like `AddComponentControl`, placing array `.push()` groupings into dictionaries and `.sort()` operations directly in the render body creates new objects and arrays on every keystroke or local state change (e.g. `setPicked`), severely impacting performance in lists.
**Action:** Always wrap grouping (e.g., `byCategory` dictionaries) and sorting (e.g., `categories.sort()`) of mostly-static library data inside a `useMemo` hook to avoid O(N) allocation and re-sorting during local state interactions.
## 2023-10-27 - [Avoid chained array operations for limited slices]
**Learning:** [When deriving a limited array slice from a larger filtered collection, chaining `.filter().slice()` causes an unnecessary O(N) traversal of the entire array, creating intermediate arrays that are immediately thrown away. A single-pass `for...of` loop with an early `break` is much more efficient, especially for unbounded lists like inventory search results.]
**Action:** [Always replace `.filter().slice()` chains with a single `for...of` loop and a `break` when returning a bounded array subset, keeping the code clean but performant.]
