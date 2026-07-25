import { useEffect, useMemo, useState } from "react";
import type { BoardSummary, Design } from "../types/api";
import { bootstrapDesign } from "../lib/bootstrap";
import { api } from "../api/client";
import { Button, Dialog, FieldLabel, Input } from "./ui";

interface Props {
  boards: BoardSummary[] | null;
  onCancel: () => void;
  onAdopt: (design: Design) => void;
}

// Group the picker by chip family: esp8266 first, then esp32; within a
// family, by name.
const MCU_ORDER: Record<string, number> = { esp8266: 0, esp32: 1 };

/**
 * Manual "New design" picker. Same payload shape as the USB detect flow,
 * just without the chip detection -- you pick the board you intend to
 * target and we seed a minimal design.json from it.
 */
export function NewDesignDialog({ boards, onCancel, onAdopt }: Props) {
  const [pickedBoardId, setPickedBoardId] = useState<string>("");
  const [name, setName] = useState<string>("New device");
  const [id, setId] = useState<string>("new-device");

  const sortedBoards = useMemo(() => {
    if (!boards) return boards;
    return [...boards].sort((a, b) => {
      const ra = MCU_ORDER[a.mcu] ?? 99;
      const rb = MCU_ORDER[b.mcu] ?? 99;
      return ra - rb || a.name.localeCompare(b.name);
    });
  }, [boards]);

  // Default to the first board once the list arrives.
  useEffect(() => {
    if (sortedBoards && sortedBoards.length > 0 && !pickedBoardId) {
      setPickedBoardId(sortedBoards[0].id);
    }
  }, [sortedBoards, pickedBoardId]);

  async function handleAdopt() {
    if (!boards) return;
    const board = boards.find((b) => b.id === pickedBoardId);
    if (!board) return;
    // Reuse the same bootstrap helper the USB flow uses; manual case has
    // no MAC and a chip name derived from the board's chip_variant.
    const d = bootstrapDesign(board, { chipName: board.chip_variant.toUpperCase() });
    // Override id + name with the user's pick.
    const trimmedId = id.trim() || "new-device";
    const trimmedName = name.trim() || trimmedId;
    const fleet = d.fleet as Record<string, unknown>;
    const base = {
      ...d,
      id: trimmedId,
      name: trimmedName,
      fleet: { ...fleet, device_name: trimmedId },
    };
    // Pre-populate the board's onboard peripherals. Best-effort: never
    // block creating the design on a seeding failure.
    try {
      onAdopt(await api.seedOnboard(base));
    } catch {
      onAdopt(base);
    }
  }

  return (
    <Dialog
      title="New design"
      subtitle="Pick a board; we seed a fresh design with its built-in parts. Add more from the inspector after."
      onClose={onCancel}
      footer={
        <>
          <Button onClick={onCancel}>Cancel</Button>
          <Button variant="primary" disabled={!pickedBoardId || !id.trim()} onClick={handleAdopt}>
            Create →
          </Button>
        </>
      }
    >
      <div className="space-y-4 text-sm">
        <div className="space-y-1">
          <FieldLabel>id</FieldLabel>
          <Input
            type="text"
            value={id}
            onChange={(e) => setId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
            placeholder="new-device"
            className="font-mono text-xs"
          />
          <p className="text-[11px] text-ink-faint">
            Used as the saved-design id and the ESPHome device name. Lowercase letters,
            digits, and dashes only.
          </p>
        </div>

        <div className="space-y-1">
          <FieldLabel>name</FieldLabel>
          <Input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="New device"
          />
        </div>

        <div className="space-y-1">
          <FieldLabel>board</FieldLabel>
          {sortedBoards === null ? (
            <div className="text-xs text-ink-faint">loading boards…</div>
          ) : sortedBoards.length === 0 ? (
            <div className="text-xs text-ink-faint">no boards in the library</div>
          ) : (
            <ul className="max-h-72 space-y-1.5 overflow-y-auto">
              {sortedBoards.map((b) => (
                <li key={b.id}>
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-lg border px-2.5 py-2 transition-colors ${
                      pickedBoardId === b.id
                        ? "border-accent-500/50 bg-accent-500/5"
                        : "border-line bg-surface-2/40 hover:border-line-strong hover:bg-surface-2"
                    }`}
                  >
                    <input
                      type="radio"
                      name="board"
                      value={b.id}
                      checked={pickedBoardId === b.id}
                      onChange={() => setPickedBoardId(b.id)}
                      className="h-3.5 w-3.5"
                    />
                    {b.image ? (
                      <img
                        src={b.image}
                        alt=""
                        loading="lazy"
                        onError={(e) => {
                          (e.currentTarget as HTMLImageElement).style.visibility = "hidden";
                        }}
                        className="h-10 w-10 shrink-0 rounded-md bg-white/5 object-contain"
                      />
                    ) : (
                      <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-surface-2 text-[9px] text-ink-ghost">
                        no img
                      </div>
                    )}
                    <span className="flex-1 text-xs">
                      <span className="text-ink">{b.name}</span>
                      <span className="ml-2 text-ink-faint">
                        {b.chip_variant} · {b.framework}
                        {b.flash_size_mb ? ` · ${b.flash_size_mb}MB` : ""}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Dialog>
  );
}
