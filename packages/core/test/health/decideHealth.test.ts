import { describe, expect, it } from "vitest";

import { decideHealth } from "../../src/health/decideHealth.ts";

describe("decideHealth", () => {
  it("is healthy when every probe passes", () => {
    const health = decideHealth([{ name: "sqlite", ok: true }]);
    expect(health).toEqual({ kind: "healthy", checked: ["sqlite"] });
  });

  it("is degraded and names the failing probes", () => {
    const health = decideHealth([
      { name: "sqlite", ok: true },
      { name: "latex", ok: false },
    ]);
    expect(health).toEqual({ kind: "degraded", failing: ["latex"] });
  });
});
