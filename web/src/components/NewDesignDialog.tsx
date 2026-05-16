import { useEffect, useState } from "react";
import type { BoardSummary, Design } from "../types/api";
import { bootstrapDesign } from "../lib/bootstrap";

interface Props {
  boards: BoardSummary[] | null;
  onCancel: () => void;
  onAdopt: (design: Design) => void;
}

/**
 * Manual "New design" picker. Same payload shape as the USB detect flow,
 * just without the chip detection -- you pick the board you intend to
 * target and we seed a minimal design.json from it.
 */
export function NewDesignDialog({ boards, onCancel, onAdopt }: Props) {
  const [pickedBoardId, setPickedBoardId] = useState<string>("");
  const [name, setName] = useState<string>("New device");
  const [id, setId] = useState<string>("new-device");

  // Default to the first board once the list arrives.
  useEffect(() => {
    if (boards && boards.length > 0 && !pickedBoardId) {
      setPickedBoardId(boards[0].id);
    }
  }, [boards, pickedBoardId]);

  function handleAdopt() {
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
    onAdopt({
      ...d,
      id: trimmedId,
      name: trimmedName,
      fleet: { ...fleet, device_name: trimmedId },
    });
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="m-4 max-h-[85vh] w-full max-w-xl overflow-hidden rounded-lg border border-zinc-800 bg-zinc-950 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-zinc-800 px-4 py-3">
          <div>
            <div className="text-sm font-semibold text-zinc-100">New design</div>
            <div className="text-xs text-zinc-500">
              Pick a board and seed a fresh, empty design. Add components from the inspector after.
            </div>
          </div>
          <button
            onClick={onCancel}
            className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
          >
            Close
          </button>
        </div>

        <div className="space-y-4 p-4 text-sm">
          <div className="space-y-1">
            <label className="block text-[11px] uppercase tracking-wide text-zinc-500">id</label>
            <input
              type="text"
              value={id}
              onChange={(e) => setId(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, "-"))}
              placeholder="new-device"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:border-zinc-600 focus:outline-none"
            />
            <p className="text-[11px] text-zinc-500">
              Used as the saved-design id and the ESPHome device name. Lowercase letters,
              digits, and dashes only.
            </p>
          </div>

          <div className="space-y-1">
            <label className="block text-[11px] uppercase tracking-wide text-zinc-500">name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="New device"
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-2 py-1.5 text-sm text-zinc-100 focus:border-zinc-600 focus:outline-none"
            />
          </div>

          <div className="space-y-1">
            <label className="block text-[11px] uppercase tracking-wide text-zinc-500">board</label>
            {boards === null ? (
              <div className="text-xs text-zinc-500">loading boards…</div>
            ) : boards.length === 0 ? (
              <div className="text-xs text-zinc-500">no boards in the library</div>
            ) : (
              <ul className="max-h-72 space-y-1.5 overflow-y-auto">
                {boards.map((b) => (
                  <li key={b.id}>
                    <label className="flex cursor-pointer items-center gap-3 rounded border border-zinc-800 bg-zinc-900/40 px-2 py-1.5 hover:bg-zinc-900">
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
                          className="h-10 w-10 shrink-0 rounded bg-white/5 object-contain"
                        />
                      ) : (
                        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded bg-zinc-800/60 text-[9px] text-zinc-600">
                          no img
                        </div>
                      )}
                      <span className="flex-1 text-xs">
                        <span className="text-zinc-100">{b.name}</span>
                        <span className="ml-2 text-zinc-500">
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

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onCancel}
              className="rounded border border-zinc-800 px-2 py-1 text-xs text-zinc-300 hover:bg-zinc-900"
            >
              Cancel
            </button>
            <button
              disabled={!pickedBoardId || !id.trim()}
              onClick={handleAdopt}
              className="rounded bg-blue-500/20 px-3 py-1.5 text-sm text-blue-100 ring-1 ring-blue-400/40 enabled:hover:bg-blue-500/30 disabled:opacity-40"
            >
              Create →
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
