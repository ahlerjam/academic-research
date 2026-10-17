/** Selftest fixture function. */
export function run(r: { kind: "a" } | { kind: "b" }): number {
  switch (r.kind) {
    case "a":
      return 1;
    case "b":
      return 2;
  }
}
