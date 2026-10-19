import { serve } from "@hono/node-server";

import { nodeRuntime } from "./adapters/runtime.ts";
import { createApp } from "./app.ts";

const app = createApp({ runtime: nodeRuntime(24) });

// constraint: bind to loopback only; hosted mode adds its own reverse proxy (plan section 4.10)
serve({ fetch: app.fetch, hostname: "127.0.0.1", port: Number(process.env["PORT"] ?? 4317) });
