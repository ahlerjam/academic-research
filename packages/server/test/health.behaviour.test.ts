import { describe, expect, it } from "vitest";

import { fakeRuntime } from "../src/adapters/runtime.fake.ts";
import { translateNodeVersion } from "../src/adapters/runtime.ts";
import { createApp } from "../src/app.ts";

describe("health", () => {
  it("answers 200 and healthy when the runtime probe passes", async () => {
    const response = await createApp({ runtime: fakeRuntime(true) }).request("/health");
    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ kind: "healthy", checked: ["node"] });
  });

  it("answers 503 and names the failing probe", async () => {
    const response = await createApp({ runtime: fakeRuntime(false) }).request("/health");
    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ kind: "degraded", failing: ["node"] });
  });

  it("translates a Node.js version into its major number", () => {
    const major = translateNodeVersion("24.14.1");
    expect(major).toBe(24);
    const unreadable = translateNodeVersion("x");
    expect(unreadable).toBe(0);
  });
});
