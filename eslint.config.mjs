// @ts-check
import js from "@eslint/js";
import tseslint from "typescript-eslint";

const noNodeInCore = {
  patterns: [
    {
      group: ["node:*", "fs", "path", "os", "child_process", "net", "http", "https", "crypto"],
      message: "core is pure: pass data in from a flow [TS-CORE-PURE]",
    },
    {
      group: ["@academic-research/server", "@academic-research/web", "**/server/**", "**/web/**"],
      message: "core never imports server or web [TS-CORE-PURE]",
    },
  ],
};

export default tseslint.config(
  { ignores: ["**/node_modules/**", "**/dist/**", "**/coverage/**", "gates/**", "fixtures/**", "**/*.d.ts"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  ...tseslint.configs.stylisticTypeChecked,
  {
    languageOptions: { parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname } },
    linterOptions: { reportUnusedDisableDirectives: "error", noInlineConfig: false },
    rules: {
      "@typescript-eslint/no-explicit-any": "error",
      "@typescript-eslint/explicit-module-boundary-types": "error",
      "@typescript-eslint/switch-exhaustiveness-check": "error",
      "@typescript-eslint/consistent-type-definitions": ["error", "type"],
      "@typescript-eslint/no-floating-promises": "error",
      "@typescript-eslint/only-throw-error": "error",
      "@typescript-eslint/ban-ts-comment": [
        "error",
        { "ts-expect-error": true, "ts-ignore": true, "ts-nocheck": true, "ts-check": false },
      ],
      "no-console": "error",
      eqeqeq: "error",
      "no-restricted-syntax": ["error", { selector: "TSEnumDeclaration", message: "use a union of string literals" }],
    },
  },
  { files: ["packages/core/src/**/*.ts"], rules: { "no-restricted-imports": ["error", noNodeInCore] } },
  {
    files: ["packages/web/src/**/*.ts"],
    rules: {
      "no-restricted-properties": [
        "error",
        { property: "innerHTML", message: "render text nodes; HTML strings open XSS [TS-NO-INNERHTML]" },
        { property: "outerHTML", message: "render text nodes; HTML strings open XSS [TS-NO-INNERHTML]" },
      ],
    },
  },
  { files: ["**/*.js", "**/*.mjs"], extends: [tseslint.configs.disableTypeChecked] },
);
