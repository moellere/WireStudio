import { useState } from "react";
import { Share2 } from "lucide-react";
import { api, ApiError } from "../api/client";
import type { CommunityStatus, LibraryCollection } from "../types/api";
import { downloadBlob, parseTags, rememberHandle, storedHandle } from "../lib/share";
import { Button, Dialog, FieldLabel, Input } from "./ui";

/** Packs a user component or board as the folder the catalogue's library/
 *  expects and opens its upload page, as ShareDialog does for a design. */
export function LibraryShareDialog({ kind, id, status, onClose }: {
  kind: LibraryCollection;
  id: string;
  status: CommunityStatus;
  onClose: () => void;
}) {
  const [author, setAuthor] = useState(storedHandle());
  const [tags, setTags] = useState("");
  const [source, setSource] = useState("");
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const handle = author.trim().replace(/^@/, "");
  const noun = kind === "boards" ? "board" : "component";

  async function share() {
    setBusy(true);
    setError(null);
    try {
      const blob = await api.communityShareLibrary({
        kind, id, author: handle, tags: parseTags(tags), source: source.trim(), notes,
      });
      rememberHandle(handle);
      downloadBlob(blob, `${id}.zip`);
      window.open(`${status.library_upload_url}/${kind}`, "_blank", "noopener");
      setDone(true);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      title={`Share ${id} to the community library`}
      subtitle={<>Library entries in <code className="font-mono">{status.repo}</code> are {status.library_license}: anyone may use them, and a maintainer may promote one into WireStudio's bundled library, crediting you.</>}
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
          <li>Unzip the download. It holds one folder, <span className="font-mono">{id}</span>.</li>
          <li>Drag that folder onto the GitHub page that just opened.</li>
          <li>Commit to a new branch and open the pull request GitHub offers.</li>
          <li>CI runs the same {noun} gate; a maintainer reviews and merges it.</li>
        </ol>
      ) : (
        <div className="space-y-3 text-sm text-ink-dim">
          <div>
            <FieldLabel>Your GitHub handle</FieldLabel>
            <Input autoFocus value={author} placeholder="octocat" onChange={(e) => setAuthor(e.target.value)} />
          </div>
          <div>
            <FieldLabel>Tags</FieldLabel>
            <Input value={tags} placeholder={kind === "boards" ? "esp32s2, usb-c" : "sensor, i2c"} onChange={(e) => setTags(e.target.value)} />
          </div>
          <div>
            <FieldLabel>Datasheet or product page (https)</FieldLabel>
            <Input value={source} placeholder="https://..." onChange={(e) => setSource(e.target.value)} />
            <p className="mt-1 text-xs text-ink-faint">What the reviewer checks the pinout and ratings against.</p>
          </div>
          <div>
            <FieldLabel>Notes (optional, becomes the README)</FieldLabel>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={4}
              placeholder={`Where the data comes from, whether you have used this ${noun}, anything to watch for.`}
              className="w-full rounded-md border border-line bg-surface-1 px-2.5 py-1.5 text-sm text-ink placeholder:text-ink-ghost transition-colors focus:border-accent-500/60 focus:outline-none"
            />
          </div>
          <p className="text-xs text-ink-faint">
            See{" "}
            <a className="underline" href={status.contributing_url} target="_blank" rel="noreferrer">the contribution rules</a>.
          </p>
          {error && <p className="text-xs text-rose-300">{error}</p>}
        </div>
      )}
    </Dialog>
  );
}
