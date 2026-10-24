import { useState } from "react";
import { Share2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { CommunityStatus, Design } from "../types/api";
import { Button, Dialog, FieldLabel, Input } from "./ui";
import { MAX_PHOTOS, downloadBlob, parseTags, rememberHandle, storedHandle, toBase64 } from "../lib/share";

/** Packs the design as the folder the catalogue's CI expects and opens its
 *  upload page. The studio holds no GitHub token: the user uploads the
 *  folder and opens the pull request from their own account. */
export function ShareDialog({ design, status, onClose }: {
  design: Design;
  status: CommunityStatus;
  onClose: () => void;
}) {
  const [author, setAuthor] = useState(storedHandle());
  const [tags, setTags] = useState("");
  const [notes, setNotes] = useState("");
  const [photos, setPhotos] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const handle = author.trim().replace(/^@/, "");
  const origin = design.origin as { author?: string; slug?: string } | undefined;

  async function share() {
    setBusy(true);
    setError(null);
    try {
      const encoded = await Promise.all(photos.map(async (f) => ({ name: f.name, data: await toBase64(f) })));
      const blob = await api.communityShare({ design, author: handle, tags: parseTags(tags), notes, photos: encoded });
      rememberHandle(handle);
      downloadBlob(blob, `${String(design.id ?? "design")}.zip`);
      window.open(status.upload_url, "_blank", "noopener");
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title="Share to the community catalogue"
      subtitle={<>Designs in <code className="font-mono">{status.repo}</code> are {status.license}: anyone may use and adapt them, crediting you.</>}
      onClose={onClose}
      maxWidth="max-w-lg"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button onClick={onClose}>{done ? "Close" : "Cancel"}</Button>
          {!done && (
            <Button variant="primary" disabled={!handle || busy} onClick={share}>
              <Share2 className="h-3.5 w-3.5" />
              {busy ? "Packing..." : "Download and open GitHub"}
            </Button>
          )}
        </div>
      }
    >
      {done ? (
        <ol className="list-decimal space-y-2 pl-5 text-sm text-ink-dim">
          <li>Unzip the download. It holds one folder, named after the design.</li>
          <li>Drag that folder onto the GitHub page that just opened.</li>
          <li>Commit to a new branch and open the pull request GitHub offers.</li>
          <li>CI checks the design; a maintainer reviews and merges it.</li>
        </ol>
      ) : (
        <div className="space-y-3 text-sm text-ink-dim">
          {origin?.slug && (
            <p>
              Imported from <span className="font-mono">{origin.slug}</span> by @{origin.author}; the
              catalogue will credit it as the design yours is derived from.
            </p>
          )}
          <div>
            <FieldLabel>Your GitHub handle</FieldLabel>
            <Input autoFocus value={author} placeholder="octocat" onChange={(e) => setAuthor(e.target.value)} />
          </div>
          <div>
            <FieldLabel>Tags</FieldLabel>
            <Input value={tags} placeholder="climate, oled, battery" onChange={(e) => setTags(e.target.value)} />
          </div>
          <div>
            <FieldLabel>Notes (optional, becomes the README)</FieldLabel>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder="What it does, whether you built it, anything to watch for."
              className="w-full rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none"
            />
          </div>
          <div>
            <FieldLabel>Photos of the build (optional, up to {MAX_PHOTOS})</FieldLabel>
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp"
              multiple
              aria-label="Photos of the build"
              onChange={(e) => setPhotos(Array.from(e.target.files ?? []).slice(0, MAX_PHOTOS))}
              className="block w-full text-xs text-ink-dim file:mr-2 file:rounded-md file:border-0 file:bg-surface-2 file:px-2 file:py-1 file:text-xs file:text-ink"
            />
            {photos.length > 0 && (
              <p className="mt-1 text-xs text-ink-faint">{photos.map((f) => f.name).join(", ")}</p>
            )}
            <p className="mt-1 text-xs text-ink-faint">
              The device, its wiring or enclosure; no people. The studio shrinks each photo and strips its
              metadata, including any GPS location, before packing it.
            </p>
          </div>
          <p className="text-xs text-ink-faint">
            Wi-Fi, API and LoRaWAN keys must be <code className="font-mono">!secret</code> references;
            sharing refuses a design that holds a literal one. See{" "}
            <a className="underline" href={status.contributing_url} target="_blank" rel="noreferrer">the contribution rules</a>.
          </p>
          {error && <p className="text-xs text-rose-300">{error}</p>}
        </div>
      )}
    </Dialog>
  );
}
