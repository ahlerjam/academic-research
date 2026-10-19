import { Hono } from "hono";

import type { RuntimePort } from "../adapters/runtime.ts";
import { checkHealth } from "./flow.ts";

const statusOf = { healthy: 200, degraded: 503 } as const;

/** Routes of the health feature: GET /health (operation getHealth). */
export function healthRoutes(runtime: RuntimePort): Hono {
  const routes = new Hono();
  routes.get("/health", async (c) => {
    const health = await checkHealth(runtime);
    return c.json(health, statusOf[health.kind]);
  });
  return routes;
}
