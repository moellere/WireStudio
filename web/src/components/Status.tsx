import type { ReactNode } from "react";

/**
 * Shared loading + empty placeholders. One animated spinner / one empty
 * state across every panel, so the UI doesn't drift into a mix of bare
 * "loading..." text and styled states.
 */
export function Loading() {
  return (
    <div className="flex items-center justify-center py-8 text-xs text-zinc-500">
      <span className="flex items-center gap-2">
        <span className="relative flex h-2 w-2">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-zinc-500 opacity-75" />
          <span className="relative inline-flex h-2 w-2 rounded-full bg-zinc-600" />
        </span>
        Loading...
      </span>
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="flex items-center justify-center py-8 text-center text-sm text-zinc-500">
      {children}
    </div>
  );
}
