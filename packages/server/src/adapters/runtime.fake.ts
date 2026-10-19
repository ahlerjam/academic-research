import type { RuntimePort } from "./runtime.ts";

/** In-memory runtime double whose probe result the test chooses. */
export function fakeRuntime(ok: boolean): RuntimePort {
  return { probe: () => Promise.resolve({ name: "node", ok }) };
}
