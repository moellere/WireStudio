import { useEffect, useState } from "react";

const STORAGE_KEY = "wirestudio:ui:advanced";

function readInitial(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

export function useAdvancedMode(): [boolean, (next: boolean) => void] {
  const [advanced, setAdvanced] = useState<boolean>(readInitial);

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, advanced ? "1" : "0");
    } catch {
      // Quota / private browsing -- in-memory state still works for this session.
    }
  }, [advanced]);

  return [advanced, setAdvanced];
}
