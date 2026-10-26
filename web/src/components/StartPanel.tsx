import type { ComponentType } from "react";
import { Cpu, FolderOpen, Usb } from "lucide-react";
import type { SavedDesignSummary } from "../types/api";
import { ListRow, Notice, Section } from "./ui";

interface Props {
  exampleCount: number;
  boardCount: number;
  saved: SavedDesignSummary[] | null;
  error: string | null;
  onOpenExample: () => void;
  onNewFromBoard: () => void;
  onConnectDevice: () => void;
  onOpenSaved: (id: string) => void;
}

export function StartPanel({
  exampleCount, boardCount, saved, error,
  onOpenExample, onNewFromBoard, onConnectDevice, onOpenSaved,
}: Props) {
  const recent = [...(saved ?? [])]
    .sort((a, b) => b.saved_at.localeCompare(a.saved_at))
    .slice(0, 4);

  return (
    <section className="min-h-0 min-w-0 overflow-auto">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-8 py-12">
        <div className="space-y-1">
          <h2 className="text-base font-semibold text-ink">Start a design</h2>
          <p className="text-sm text-ink-dim">
            One <code className="font-mono text-xs text-ink">design.json</code> drives the YAML,
            wiring, schematic, PCB, fab bundle and enclosure.
          </p>
        </div>

        {error && (
          <Notice tone="rose" title="Could not open that design">
            <div className="mt-1 whitespace-pre-wrap">{error}</div>
          </Notice>
        )}

        <div className="grid grid-cols-1 gap-4 @2xl:grid-cols-3">
          <StartCard
            icon={FolderOpen}
            title="Open an example"
            body="Every library board and component is exercised by a bundled example that passes the YAML, schematic, PCB and enclosure gates."
            meta={`${exampleCount} examples`}
            onClick={onOpenExample}
            disabled={exampleCount === 0}
          />
          <StartCard
            icon={Cpu}
            title="New from a board"
            body="Pick a board; its onboard peripherals are seeded and wired. Then add components by function."
            meta={`${boardCount} boards`}
            onClick={onNewFromBoard}
          />
          <StartCard
            icon={Usb}
            title="Connect a device"
            body="Detect a plugged-in ESP over WebSerial. The chip is matched to a board family and its peripherals are populated."
            meta="WebSerial · esptool-js"
            onClick={onConnectDevice}
          />
        </div>

        {recent.length > 0 && (
          <Section title="Recent">
            <ul className="grid grid-cols-1 gap-1.5 text-sm @2xl:grid-cols-2">
              {recent.map((d) => (
                <li key={d.id}>
                  <ListRow onClick={() => onOpenSaved(d.id)}>
                    <div className="truncate font-medium text-ink">{d.name || d.id}</div>
                    <div className="mt-1 truncate text-xs text-ink-faint">
                      <span className="font-mono">{d.id}</span> · {d.board_library_id}
                    </div>
                  </ListRow>
                </li>
              ))}
            </ul>
          </Section>
        )}
      </div>
    </section>
  );
}

function StartCard({
  icon: Icon, title, body, meta, onClick, disabled = false,
}: {
  icon: ComponentType<{ className?: string }>;
  title: string;
  body: string;
  meta: string;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="flex flex-col gap-3 rounded-xl border border-line bg-surface-1 p-5 text-left transition-colors enabled:hover:border-line-strong enabled:hover:bg-surface-2 disabled:opacity-40"
    >
      <Icon className="h-5 w-5 text-accent-300" />
      <span className="text-sm font-semibold text-ink">{title}</span>
      <span className="text-xs leading-relaxed text-ink-dim">{body}</span>
      <span className="font-mono text-[11px] text-ink-faint">{meta}</span>
    </button>
  );
}
