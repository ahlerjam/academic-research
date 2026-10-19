import { Hono } from "hono";

import type { RuntimePort } from "./adapters/runtime.ts";
import { healthRoutes } from "./health/api.ts";

/** The ports the application needs; main.ts passes real adapters, tests pass fakes. */
export type Ports = { readonly runtime: RuntimePort };

/** Wire every feature's routes into one application. */
export function createApp(ports: Ports): Hono {
  const app = new Hono();
  app.route("/", healthRoutes(ports.runtime));
  return app;
}
