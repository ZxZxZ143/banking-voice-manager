import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig, loadEnv } from "vite";
import { analyticsProxy } from "./server/analyticsProxy.ts";

export default defineConfig(({ mode }) => {
  // Only server configuration reads these non-VITE variables. No credential enters define().
  const env = {
    ...loadEnv(
      mode,
      fileURLToPath(new URL("..", import.meta.url)),
      "ANALYTICS_",
    ),
    ...process.env,
  };
  const supervisor = analyticsProxy(
    env.ANALYTICS_API_TOKEN ?? "",
    env.ANALYTICS_PROXY_TARGET,
  );
  const proxy = {
    "/analytics-api": supervisor.options,
    "/health": { target: "http://127.0.0.1:8000" },
    "/api": { target: "http://127.0.0.1:8000", ws: true },
  };
  return {
    plugins: [react(), tailwindcss(), supervisor.plugin],
    define: {
      __ANALYTICS_DEMO_DATA__: JSON.stringify(
        env.ANALYTICS_DEMO_ENABLED === "true",
      ),
    },
    resolve: {
      alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
    },
    server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
    preview: { host: "127.0.0.1", port: 4173, strictPort: true, proxy },
  };
});
