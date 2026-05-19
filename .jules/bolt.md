## 2024-05-17 - React Drag-and-Drop Re-renders
**Learning:** High-frequency events like drag-and-drop in React (e.g., in `PinoutView.tsx`) can severely degrade performance if expensive synchronous operations (like building large Maps for dependency lookups) are executed directly in the render body instead of being memoized.
**Action:** Always wrap derived state computations (filters, maps, object key extractions) in `useMemo` when working in components that render lists or respond to high-frequency DOM events.

## 2024-05-18 - Stable Array References from design.ts Readers
**Learning:** Helper functions like `readComponents` or `readConnections` in `web/src/lib/design.ts` map over the raw `Design` object and return *new* array references on every call. If called directly in the body of a React component, they defeat any downstream `useMemo` hooks (e.g., in `PinoutView.tsx` drag-and-drop), causing expensive re-computations on every render.
**Action:** Always wrap the return values of `read*` helpers in `useMemo(..., [design])` at the call site within a React component.
