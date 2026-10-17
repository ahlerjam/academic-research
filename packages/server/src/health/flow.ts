import { decideHealth, type Health } from "@academic-research/core";

import type { RuntimePort } from "../adapters/runtime.ts";

/** Load every probe, decide the health in the core and return it. */
export async function checkHealth(runtime: RuntimePort): Promise<Health> {
  const probes = [await runtime.probe()];
  return decideHealth(probes);
}
