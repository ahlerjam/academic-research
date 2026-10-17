/** Render the application shell into the root element using text nodes only (no HTML strings). */
export function renderShell(root: HTMLElement): void {
  const heading = document.createElement("h1");
  heading.textContent = "academic-research";
  root.replaceChildren(heading);
}
