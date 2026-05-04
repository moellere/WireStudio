import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api/client";
import type { AgentToolCall, Design } from "../types/api";

interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  toolCalls?: AgentToolCall[];
  isError?: boolean;
}

interface Props {
  open: boolean;
  design: Design | null;
  onClose: () => void;
  onDesignReplaced: (next: Design) => void;
}

export function AgentSidebar({ open, design, onClose, onDesignReplaced }: Props) {
  const [status, setStatus] = useState<{ available: boolean; reason: string | null } | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Probe agent availability whenever the drawer opens.
  useEffect(() => {
    if (!open) return;
    api.agentStatus().then(setStatus).catch(() => setStatus({ available: false, reason: "could not reach the API" }));
  }, [open]);

  // Auto-scroll the chat when messages or pending state changes.
  useEffect(() => {
    if (!open || !scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [messages, pending, open]);

  async function handleSend() {
    const text = draft.trim();
    if (!text || !design || pending) return;
    setError(null);
    setMessages((prev) => [...prev, { role: "user", text }]);
    setDraft("");
    setPending(true);
    try {
      const r = await api.agentTurn({ session_id: sessionId, design, message: text });
      setSessionId(r.session_id);
      onDesignReplaced(r.design);
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: r.assistant_text || "(no reply)",
          toolCalls: r.tool_calls,
        },
      ]);
    } catch (e) {
      const msg = e instanceof ApiError
        ? `${e.status}: ${e.message}`
        : e instanceof Error ? e.message : String(e);
      setMessages((prev) => [...prev, { role: "assistant", text: msg, isError: true }]);
      setError(msg);
    } finally {
      setPending(false);
    }
  }

  function handleNewSession() {
    setSessionId(null);
    setMessages([]);
    setError(null);
  }

  if (!open) return null;

  return (
    <aside className="fixed inset-y-0 right-0 z-40 flex w-[28rem] max-w-[90vw] flex-col border-l border-zinc-800 bg-zinc-950 shadow-2xl">
      <header className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
        <div>
          <div className="text-sm font-semibold text-zinc-100">Agent</div>
          <div className="mt-0.5 truncate text-[11px] text-zinc-500">
            {sessionId ? `session ${sessionId}` : "new session"}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleNewSession}
            disabled={messages.length === 0}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 enabled:hover:bg-zinc-900 disabled:opacity-40"
            title="Start a fresh conversation"
          >
            New
          </button>
          <button
            onClick={onClose}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>
      </header>

      <div ref={scrollRef} className="min-h-0 flex-1 space-y-3 overflow-auto p-4 text-sm">
        {status && !status.available && (
          <div className="rounded border border-amber-500/40 bg-amber-500/10 p-3 text-xs text-amber-100">
            <div className="mb-1 font-semibold">Agent unavailable</div>
            <div className="whitespace-pre-wrap">{status.reason}</div>
          </div>
        )}

        {messages.length === 0 && status?.available && (
          <Welcome />
        )}

        {messages.map((m, i) => (
          <Bubble key={i} message={m} />
        ))}

        {pending && (
          <div className="text-xs italic text-zinc-500">agent thinking…</div>
        )}
      </div>

      <div className="border-t border-zinc-800 p-3">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
              e.preventDefault();
              handleSend();
            }
          }}
          rows={3}
          placeholder={status?.available ? "Ask the agent... (⌘/Ctrl+Enter)" : "Agent unavailable"}
          disabled={!status?.available || pending}
          className="w-full resize-none rounded border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-zinc-600 focus:outline-none disabled:opacity-50"
        />
        <div className="mt-2 flex items-center justify-between">
          <div className="text-[11px] text-zinc-500">
            {error ? <span className="text-red-300">{error}</span> : "Edits go directly into the live design."}
          </div>
          <button
            onClick={handleSend}
            disabled={!status?.available || pending || !draft.trim()}
            className="rounded bg-blue-500/20 px-3 py-1 text-xs text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </aside>
  );
}

function Welcome() {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3 text-xs text-zinc-400">
      <div className="mb-1.5 font-semibold text-zinc-200">Talk to the design</div>
      <p>The agent can search the library, add or remove components, set
      params, change boards, and edit connections. It edits your current
      design in place — your live YAML and ASCII update as it goes.</p>
      <ul className="mt-2 list-disc space-y-0.5 pl-4">
        <li>"add a BME280 over I2C"</li>
        <li>"swap the pir to GPIO5"</li>
        <li>"what would I need for an outdoor weather station?"</li>
        <li>"validate the design"</li>
      </ul>
    </div>
  );
}

function Bubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
      <div
        className={`max-w-[85%] rounded px-3 py-2 ${
          message.isError
            ? "border border-red-500/40 bg-red-500/10 text-red-200"
            : isUser
              ? "bg-blue-500/15 text-blue-100 ring-1 ring-blue-400/30"
              : "bg-zinc-900 text-zinc-200 ring-1 ring-zinc-800"
        }`}
      >
        <div className="whitespace-pre-wrap text-sm">{message.text}</div>
        {message.toolCalls && message.toolCalls.length > 0 && (
          <details className="mt-2 text-[11px] text-zinc-500">
            <summary className="cursor-pointer hover:text-zinc-300">
              {message.toolCalls.length} tool call{message.toolCalls.length === 1 ? "" : "s"}
            </summary>
            <ul className="mt-1 space-y-1 font-mono">
              {message.toolCalls.map((tc, i) => (
                <li key={i} className={tc.is_error ? "text-red-300" : "text-zinc-400"}>
                  {tc.tool}({summarizeInput(tc.input)})
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </div>
  );
}

function summarizeInput(input: Record<string, unknown>): string {
  const entries = Object.entries(input).slice(0, 3);
  const parts = entries.map(([k, v]) => {
    const summarized = typeof v === "string" || typeof v === "number" || typeof v === "boolean"
      ? JSON.stringify(v)
      : "{...}";
    return `${k}: ${summarized}`;
  });
  if (Object.keys(input).length > 3) parts.push("...");
  return parts.join(", ");
}
