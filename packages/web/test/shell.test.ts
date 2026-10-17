// @vitest-environment jsdom
import { describe, expect, it } from "vitest";

import { renderShell } from "../src/shell.ts";

describe("renderShell", () => {
  it("renders the product name as text", () => {
    const root = document.createElement("main");
    renderShell(root);
    expect(root.textContent).toBe("academic-research");
  });
});
