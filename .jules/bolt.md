## 2024-05-17 - React Drag-and-Drop Re-renders
**Learning:** High-frequency events like drag-and-drop in React (e.g., in `PinoutView.tsx`) can severely degrade performance if expensive synchronous operations (like building large Maps for dependency lookups) are executed directly in the render body instead of being memoized.
**Action:** Always wrap derived state computations (filters, maps, object key extractions) in `useMemo` when working in components that render lists or respond to high-frequency DOM events.

## 2024-05-18 - Stable Array References from design.ts Readers
**Learning:** Helper functions like `readComponents` or `readConnections` in `web/src/lib/design.ts` map over the raw `Design` object and return *new* array references on every call. If called directly in the body of a React component, they defeat any downstream `useMemo` hooks (e.g., in `PinoutView.tsx` drag-and-drop), causing expensive re-computations on every render.
**Action:** Always wrap the return values of `read*` helpers in `useMemo(..., [design])` at the call site within a React component.

## 2024-05-20 - React Hooks and Early Returns
**Learning:** When moving derived state computations into `useMemo` hooks inside components that had early returns (like `if (rows.length === 0)`), you must move the early return *after* the hooks to avoid violating React's rules of hooks (hooks cannot be called conditionally).
**Action:** When adding hooks to an existing component, always check for early returns and ensure all hooks are called unconditionally before any early returns.

## 2024-05-21 - Derived State Memoization Splitting
**Learning:** In React components receiving high-frequency updates (e.g. `ConnectionForm.tsx` where `design` changes frequently during drag-and-drop), derived state that depends on *static* or *infrequent* data (like `libraryComponents`) mixed with frequent data (like `design`) in a single `useMemo` forces the expensive static computation to run on every frequent update.
**Action:** When a computation has both static/infrequent dependencies and high-frequency dependencies, split it into two `useMemo` hooks. Compute the static/infrequent part first (e.g., building a `Set` from a large array), and then use that memoized result in the second `useMemo` that depends on the high-frequency data.

## 2024-05-23 - Rules of Hooks Violation inside JSX IIFE
**Learning:** Found a case in `CapabilityPickerDialog.tsx` where a `useMemo` was placed inside an immediately invoked function expression (IIFE) within the JSX return block. This IIFE had conditional early returns (e.g. `if (!activeQuery) return null;`) before the hook, causing a violation of the Rules of Hooks ("Rendered more hooks than during the previous render").
**Action:** Never place React hooks inside inline functions, IIFEs, conditionals, or loops. Always keep hooks unconditionally at the top level of the component and use ternary fallbacks (like `matches ? matches.filter(...) : []`) to safely handle data dependencies that might be undefined or null early in the render cycle.

## 2024-05-24 - Intermediate Array Allocation in Render Loops
**Learning:** Chaining `.filter().map()` inside a frequently re-rendered list (like `pinNames.map()` inside `PinoutView.tsx` during drag-and-drop) allocates intermediate arrays for every item on every render, which creates unnecessary garbage collection pressure and hurts rendering performance.
**Action:** Replace `.filter().map()` chains with a single `.map()` that returns `null` for filtered items, allowing React to skip rendering them without the overhead of intermediate array allocations.
## 2025-02-18 - React O(N²) array allocations in derived state lists
**Learning:** Calling `.filter()` on a list inside the `.map()` of the very same list (like finding alternatives) creates O(N²) intermediate arrays on every render. This forces unnecessary garbage collection and degrades render performance, especially as lists grow.
**Action:** Replace nested derived arrays inside render loops with lightweight logic. E.g. counting alternatives can just be `list.length - 1`, and rendering them can just map over the list and conditionally return `null`.

## 2025-02-18 - O(N²) array allocations inside render loops
**Learning:** Computing derived state, like filtering a list of compatibility warnings for every item in a list using `.filter()` inside the `.map()` loop (e.g., `warnings={compatibilityWarnings.filter((w) => w.component_id === b.id)}` in `BusList.tsx`), creates O(N²) intermediate arrays on every render. This forces unnecessary garbage collection and degrades render performance, especially as lists grow. A similar anti-pattern is creating a new filtered `Set` for every item in a loop.
**Action:** Lift the grouping of data out of the render loop into a `useMemo` map (e.g., computing a `Map<string, CompatibilityWarning[]>` where keys are component IDs). When checking for collisions, pass the entire Set to the child component and perform an `allBusIds.has(draftId)` check instead of pre-filtering the Set for each item.

## 2025-02-18 - React O(N) array lookups inside Select options map loop
**Learning:** Performing a `.find()` operation inside the `.map()` loop that renders `<option>` elements or custom labels for a `SelectInput` results in an O(N²) traversal on every render. If the array is rebuilt on every render (e.g. from `readComponents`), it adds significant garbage collection pressure on top of the CPU overhead.
**Action:** Lift the array mapping and dictionary (Map) creation out of the render loop into `useMemo` hooks. Pass the resulting O(1) lookup dictionary to the child components to avoid repetitive `.find()` lookups during render.
