/**
 * Tasmota post-flash configuration over the serial console. Commands go
 * newline-terminated at 115200 baud; Backlog0 executes the sequence
 * without inter-command delay. WiFi credentials are appended client-side
 * only -- they never touch the server or the design.
 */
export interface TasmotaTemplate {
  NAME: string;
  GPIO: number[];
  FLAG: number;
  BASE: number;
}

export function tasmotaConfigCommands(
  template: TasmotaTemplate,
  ssid?: string,
  password?: string,
): string[] {
  const cmds = [`Backlog0 Template ${JSON.stringify(template)}; Module 0`];
  if (ssid) {
    const wifi = [`SSId1 ${ssid}`];
    if (password) wifi.push(`Password1 ${password}`);
    cmds.push(`Backlog0 ${wifi.join("; ")}`);
  }
  return cmds;
}
