import { describe, expect, it } from "vitest";
import { pushMainPy, pyBytesLiteral, type SerialLike } from "./micropython";

/** A board speaking the raw REPL: answers Ctrl-A with the raw prompt and
 *  every Ctrl-D-terminated statement with OK<stdout>\x04<stderr>\x04>. */
function fakeBoard(opts: { failOn?: string } = {}) {
  const enc = new TextEncoder();
  const dec = new TextDecoder();
  const received: string[] = [];
  const files: Record<string, string> = {};
  let controller: ReadableStreamDefaultController<Uint8Array> | null = null;
  let pending = "";
  let open = "";
  const reply = (s: string) => controller?.enqueue(enc.encode(s));
  const port: SerialLike & { received: string[]; files: Record<string, string>; opened: number; closed: number } = {
    received, files, opened: 0, closed: 0,
    readable: new ReadableStream<Uint8Array>({ start(c) { controller = c; } }),
    writable: new WritableStream<Uint8Array>({
      write(chunk) {
        const text = dec.decode(chunk);
        received.push(text);
        for (const ch of text) {
          if (ch === "\x01") { pending = ""; reply("raw REPL; CTRL-B to exit\r\n>"); continue; }
          if (ch === "\x03" || ch === "\x02" || ch === "\r") continue;
          if (ch === "\x04") {
            if (!pending) continue; // soft reset in friendly mode
            const stmt = pending; pending = "";
            if (opts.failOn && stmt.includes(opts.failOn)) { reply("OK\x04Traceback: OSError: boom\x04>"); continue; }
            const m = /^f = open\("([^"]+)", 'wb'\)$/.exec(stmt);
            if (m) { open = m[1]; files[open] = ""; reply("OK\x04\x04>"); continue; }
            const w = /^f\.write\(b'(.*)'\)$/s.exec(stmt);
            if (w) { files[open] += w[1]; reply("OK\x04\x04>"); continue; }
            if (stmt.startsWith("import os")) {
              const bytes = files[open].replace(/\\x[0-9a-f]{2}|\\'|\\\\/g, "_").length;
              reply(`OK${bytes}\r\n\x04\x04>`);
              continue;
            }
            reply("OK\x04\x04>");
            continue;
          }
          pending += ch;
        }
      },
    }),
    async open() { port.opened += 1; },
    async close() { port.closed += 1; controller?.close(); },
  };
  return port;
}

describe("pyBytesLiteral", () => {
  it("escapes quotes, backslashes and control characters", () => {
    expect(pyBytesLiteral(new TextEncoder().encode("a'b\\c\n\x04"))).toBe("b'a\\'b\\\\c\\x0a\\x04'");
  });
});

describe("pushMainPy", () => {
  it("writes the file through the raw REPL, verifies its size and soft-resets", async () => {
    const port = fakeBoard();
    const log: string[] = [];
    const code = "print('hi')\n" + "x = 1\n".repeat(200);
    await pushMainPy(port, code, (l) => log.push(l));
    expect(port.files["main.py"]).toBe(pyBytesLiteral(new TextEncoder().encode(code)).slice(2, -1));
    expect(log).toEqual(["raw REPL open", `main.py written (${code.length} bytes)`, "soft reset; the board is running the new file"]);
    expect(port.received.join("")).toContain("\x02");
    expect(port.received.join("").endsWith("\x04")).toBe(true);
    expect(port.opened).toBe(1);
    expect(port.closed).toBe(1);
  });

  it("surfaces a traceback from the board and still releases the port", async () => {
    const port = fakeBoard({ failOn: "f.close()" });
    await expect(pushMainPy(port, "print(1)\n", () => {})).rejects.toThrow(/OSError: boom/);
    expect(port.closed).toBe(1);
  });

  it("times out when the board never enters the raw REPL", async () => {
    const port = fakeBoard();
    port.writable = new WritableStream<Uint8Array>({ write() { /* silent board */ } });
    await expect(pushMainPy(port, "x\n", () => {}, { timeoutMs: 100 })).rejects.toThrow(/did not answer/);
  });
});
