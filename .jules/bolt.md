## 2024-05-17 - React Drag-and-Drop Re-renders
**Learning:** High-frequency events like drag-and-drop in React (e.g., in `PinoutView.tsx`) can severely degrade performance if expensive synchronous operations (like building large Maps for dependency lookups) are executed directly in the render body instead of being memoized.
**Action:** Always wrap derived state computations (filters, maps, object key extractions) in `useMemo` when working in components that render lists or respond to high-frequency DOM events.

## 2024-05-18 - Stable Array References from design.ts Readers
**Learning:** Helper functions like `readComponents` or `readConnections` in `web/src/lib/design.ts` map over the raw `Design` object and return *new* array references on every call. If called directly in the body of a React component, they defeat any downstream `useMemo` hooks (e.g., in `PinoutView.tsx` drag-and-drop), causing expensive re-computations on every render.
**Action:** Always wrap the return values of `read*` helpers in `useMemo(..., [design])` at the call site within a React component.

## 2024-05-20 - React Hooks and Early Returns
**Learning:** When moving derived state computations into `useMemo` hooks inside components that had early returns (like `if (rows.length === 0)`), you must move the early return *after* the hooks to avoid violating React's rules of hooks (hooks cannot be called conditionally).
**Action:** When adding hooks to an existing component, always check for early returns and ensure all hooks are called unconditionally before any early returns.

## 2025-02-14 - Expensive Array Filtering in React Renders
**Learning:** Although `useMemo` was used in `CapabilityPickerDialog.tsx`, it was incorrectly nested deeply inside conditional blocks (an early return path), which violates the Rule of Hooks. Fixing this also properly guarantees that the `.filter()` operation on potentially large capability matches lists memoizes predictably, avoiding unexpected render cascade behaviors and hook index misalignment issues in React's Fiber engine.
**Action:** Lift array filtering and other `useMemo` uses to the top level of the component unconditionally, ensuring correct Rule of Hooks compliance and predictable memoization behavior.
