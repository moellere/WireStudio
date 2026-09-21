import { useState } from "react";
import { KeyRound } from "lucide-react";
import { getApiToken, setApiToken } from "../api/client";
import { Button, Dialog, FieldLabel, Input } from "./ui";

/** Shown when the API answers 401: the studio was started with
 *  WIRESTUDIO_API_TOKEN and this browser does not hold it yet. */
export function ApiTokenDialog({ onSaved, onClose }: { onSaved: () => void; onClose: () => void }) {
  const [token, setToken] = useState(getApiToken());
  const value = token.trim();

  function save() {
    if (!value) return;
    setApiToken(value);
    onSaved();
  }

  return (
    <Dialog
      title="API token required"
      subtitle="This studio only answers requests that carry its API token."
      onClose={onClose}
      maxWidth="max-w-md"
      footer={
        <div className="flex items-center justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!value} onClick={save}>
            <KeyRound className="h-3.5 w-3.5" />
            Use this token
          </Button>
        </div>
      }
    >
      <div className="space-y-3 text-sm text-ink-dim">
        <p>
          Paste the value of <code className="font-mono text-ink">WIRESTUDIO_API_TOKEN</code> from the
          server. It stays in this browser; nothing is sent anywhere but the studio API.
        </p>
        <div>
          <FieldLabel>API token</FieldLabel>
          <Input
            type="password"
            autoFocus
            value={token}
            placeholder="paste the token"
            onChange={(e) => setToken(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") save(); }}
          />
        </div>
      </div>
    </Dialog>
  );
}
