import { describe, expect, it } from "vitest";

import { PLUGIN_NAME } from "../src/index.ts";

describe("plugin package", () => {
  it("names the plugin after the product", () => {
    expect(PLUGIN_NAME).toBe("academic-research");
  });
});
