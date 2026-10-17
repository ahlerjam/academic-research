import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["packages/*/test/**/*.test.ts"],
    allowOnly: false,
    passWithNoTests: false,
    restoreMocks: true,
  },
});
