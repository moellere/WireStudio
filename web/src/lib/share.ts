/** Helpers the design and library share dialogs have in common. */
const HANDLE_KEY = "wirestudio.githubHandle";

export function storedHandle(): string {
  try {
    return localStorage.getItem(HANDLE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function rememberHandle(handle: string): void {
  try { localStorage.setItem(HANDLE_KEY, handle); } catch { /* private mode */ }
}

export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export const MAX_PHOTOS = 4;

export async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

export function parseTags(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((t) => t.trim().toLowerCase()).filter(Boolean))];
}
