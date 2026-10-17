import type { Probe } from "@academic-research/core";

/** Port for probing the runtime the server depends on. */
export type RuntimePort = { readonly probe: () => Promise<Probe> };

/** Probe the Node.js runtime: it is healthy when it runs the pinned major line. */
export function nodeRuntime(expectedMajor: number): RuntimePort {
  return {
    probe: () => Promise.resolve({ name: "node", ok: translateNodeVersion(process.versions.node) === expectedMajor }),
  };
}

/** Translate a Node.js version string into its major number, or 0 when it cannot be read. */
export function translateNodeVersion(version: string): number {
  const major = Number.parseInt(version.split(".")[0] ?? "", 10);
  return Number.isNaN(major) ? 0 : major;
}
