/**
 * Push a main.py onto a MicroPython board over WebSerial using the raw
 * REPL, the same protocol mpremote speaks: Ctrl-A enters raw mode, each
 * statement is terminated with Ctrl-D and answered `OK<stdout>\x04<stderr>\x04>`,
 * Ctrl-B leaves, Ctrl-D soft-resets so the new main.py runs. No package,
 * no firmware support needed beyond the stock REPL at 115200 baud.
 */

export interface SerialLike {
  open(opts: { baudRate: number }): Promise<void>;
  close(): Promise<void>;
  readable: ReadableStream<Uint8Array> | null;
  writable: WritableStream<Uint8Array> | null;
}

const RAW_PROMPT = "raw REPL; CTRL-B to exit\r\n>";
const CHUNK = 512;

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

/** A Python bytes literal for `data`, escaping what the raw REPL would
 *  otherwise interpret (control characters, quotes, backslashes). */
export function pyBytesLiteral(data: Uint8Array): string {
  let out = "b'";
  for (const b of data) {
    if (b === 0x27) out += "\\'";
    else if (b === 0x5c) out += "\\\\";
    else if (b >= 0x20 && b < 0x7f) out += String.fromCharCode(b);
    else out += "\\x" + b.toString(16).padStart(2, "0");
  }
  return out + "'";
}

export async function pushMainPy(
  port: SerialLike,
  code: string,
  log: (line: string) => void,
  opts: { filename?: string; timeoutMs?: number } = {},
): Promise<void> {
  const filename = opts.filename ?? "main.py";
  const timeoutMs = opts.timeoutMs ?? 5000;
  await port.open({ baudRate: 115200 });
  if (!port.readable || !port.writable) throw new Error("serial port has no streams");
  const reader = port.readable.getReader();
  const writer = port.writable.getWriter();
  const decoder = new TextDecoder();
  const encoder = new TextEncoder();
  let buf = "";
  let closed = false;
  const pump = (async () => {
    try {
      while (!closed) {
        const { value, done } = await reader.read();
        if (done) break;
        if (value) buf += decoder.decode(value, { stream: true });
      }
    } catch {
      // reader cancelled on close
    }
  })();

  const write = (s: string) => writer.write(encoder.encode(s));
  const expect = async (needle: string): Promise<string> => {
    const t0 = Date.now();
    while (!buf.includes(needle)) {
      if (Date.now() - t0 > timeoutMs) {
        throw new Error(`board did not answer with ${JSON.stringify(needle)} (got ${JSON.stringify(buf.slice(-80))})`);
      }
      await sleep(10);
    }
    const end = buf.indexOf(needle) + needle.length;
    const out = buf.slice(0, end - needle.length);
    buf = buf.slice(end);
    return out;
  };
  const exec = async (py: string): Promise<string> => {
    await write(py + "\x04");
    await expect("OK");
    const out = await expect("\x04>");
    const [stdout, stderr = ""] = out.split("\x04");
    if (stderr.trim()) throw new Error(stderr.trim());
    return stdout;
  };

  try {
    await write("\r\x03\x03");
    await sleep(50);
    buf = "";
    await write("\r\x01");
    await expect(RAW_PROMPT);
    log("raw REPL open");
    const bytes = encoder.encode(code);
    await exec(`f = open(${JSON.stringify(filename)}, 'wb')`);
    for (let i = 0; i < bytes.length; i += CHUNK) {
      await exec(`f.write(${pyBytesLiteral(bytes.subarray(i, i + CHUNK))})`);
    }
    await exec("f.close()");
    const size = (await exec(`import os; print(os.stat(${JSON.stringify(filename)})[6])`)).trim();
    log(`${filename} written (${size} bytes)`);
    await write("\x02");
    await sleep(50);
    await write("\x04");
    log("soft reset; the board is running the new file");
  } finally {
    closed = true;
    try { await reader.cancel(); } catch { /* already closed */ }
    try { reader.releaseLock(); } catch { /* already released */ }
    try { writer.releaseLock(); } catch { /* already released */ }
    await pump;
    try { await port.close(); } catch { /* already closed */ }
  }
}
