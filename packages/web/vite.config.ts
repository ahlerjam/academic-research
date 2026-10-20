import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const port = loadEnv(mode, ".", "PORT")["PORT"] ?? "4317";
  return {
    server: { host: "127.0.0.1", proxy: { "/api": `http://127.0.0.1:${port}` } },
  };
});
