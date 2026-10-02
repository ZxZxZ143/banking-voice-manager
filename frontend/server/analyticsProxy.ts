/** Node/Vite only. Never import into src/ or return the supervisor credential. */
import type { IncomingMessage, ServerResponse } from "node:http";
import type { Plugin, ProxyOptions } from "vite";

const prefix = "/analytics-api";

export function allowedRequest(
  request: Pick<IncomingMessage, "method" | "url" | "headers">,
): boolean {
  if (request.method !== "GET") return false;
  const host = request.headers.host ?? "";
  if (!/^(localhost|127\.0\.0\.1):\d{1,5}$/.test(host)) return false;
  if (request.headers.origin && request.headers.origin !== `http://${host}`)
    return false;
  if (request.headers["sec-fetch-site"] === "cross-site") return false;
  const path = (request.url ?? "").split("?")[0];
  if (
    !/^\/analytics-api\/(overview|sessions(?:\/[^/]+(?:\/journey)?)?|anomalies|scenarios|risk)$/.test(
      path,
    )
  )
    return false;
  try {
    return path.split("/").every((part) => {
      const decoded = decodeURIComponent(part);
      return decoded !== ".." && decoded !== "." && !/[\\/]/.test(decoded);
    });
  } catch {
    return false;
  }
}

export function analyticsProxy(
  token: string,
  target = "http://127.0.0.1:8000",
): { plugin: Plugin; options: ProxyOptions } {
  const origin = new URL(target);
  if (
    origin.protocol !== "http:" ||
    !["127.0.0.1", "localhost"].includes(origin.hostname) ||
    origin.username ||
    origin.password ||
    origin.pathname !== "/" ||
    origin.search ||
    origin.hash
  ) {
    throw new Error(
      "Analytics development target must be a loopback HTTP origin",
    );
  }
  const guard = (
    req: IncomingMessage,
    res: ServerResponse,
    next: () => void,
  ) => {
    if (!req.url?.startsWith(prefix)) {
      next();
      return;
    }
    res.setHeader("Cache-Control", "no-store");
    res.setHeader("Content-Type", "application/json");
    if (!allowedRequest(req)) {
      res.statusCode = 403;
      res.end(JSON.stringify({ detail: "Local supervisor access required" }));
      return;
    }
    if (!token.trim()) {
      res.statusCode = 503;
      res.end(JSON.stringify({ detail: "Supervisor proxy is not configured" }));
      return;
    }
    next();
  };
  return {
    plugin: {
      name: "local-supervisor-analytics",
      configureServer(server) {
        server.middlewares.use(guard);
      },
      configurePreviewServer(server) {
        server.middlewares.use(guard);
      },
    },
    options: {
      target: origin.origin,
      changeOrigin: true,
      rewrite: (path) => path.replace(/^\/analytics-api/, "/api/v1/analytics"),
      timeout: 15000,
      proxyTimeout: 15000,
      configure(proxy) {
        proxy.on("proxyReq", (request) => {
          request.removeHeader("authorization");
          request.setHeader("Authorization", `Bearer ${token}`);
        });
        proxy.on("proxyRes", (response) => {
          delete response.headers.authorization;
          delete response.headers["proxy-authorization"];
          response.headers["cache-control"] = "no-store";
        });
      },
    },
  };
}
