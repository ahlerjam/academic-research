import { renderShell } from "./shell.ts";

const root = document.getElementById("app");
if (root !== null) {
  renderShell(root);
}
