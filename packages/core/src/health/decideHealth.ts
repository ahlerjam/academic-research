/** The outcome of one dependency probe, as an adapter reports it. */
export type Probe = { readonly name: string; readonly ok: boolean };

/** The service health derived from all probes. */
export type Health =
  | { readonly kind: "healthy"; readonly checked: readonly string[] }
  | { readonly kind: "degraded"; readonly failing: readonly string[] };

/** Decide the service health from the probe results; any failing probe degrades it. */
export function decideHealth(probes: readonly Probe[]): Health {
  const failing = probes.filter((probe) => !probe.ok).map((probe) => probe.name);
  if (failing.length > 0) {
    return { kind: "degraded", failing };
  }
  return { kind: "healthy", checked: probes.map((probe) => probe.name) };
}
