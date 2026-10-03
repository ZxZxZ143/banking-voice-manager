import type { Filters } from "./types";
import {
  parseAnomalyPage,
  parseDetail,
  parseJourneyPage,
  parseOverview,
  parseRisk,
  parseSessionPage,
  ranked,
} from "./parse";

/** Same-origin BFF only. There is deliberately no token or authorization option. */
export class AnalyticsClient {
  constructor(
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
    private readonly timeoutMs = 12000,
    private readonly source?: Filters["source"],
  ) {}
  private async request<T>(
    path: string,
    parse: (value: unknown) => T,
    filters: Filters = {},
    signal?: AbortSignal,
  ): Promise<T> {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries({
      source: this.source,
      ...filters,
    }))
      if (value !== undefined && value !== "")
        params.set(key === "scenario" ? "assistant_id" : key, String(value));
    const controller = new AbortController();
    const cancel = () => controller.abort();
    signal?.addEventListener("abort", cancel, { once: true });
    if (signal?.aborted) controller.abort();
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, this.timeoutMs);
    try {
      const response = await this.fetcher(
        `/api/analytics/${path}${params.size ? `?${params}` : ""}`,
        {
          method: "GET",
          headers: { Accept: "application/json" },
          credentials: "same-origin",
          signal: controller.signal,
        },
      );
      if (!response.ok) {
        const message =
          response.status === 503
            ? "Analytics storage is unavailable. Check backend storage and retry."
            : response.status === 403
              ? "Supervisor access is unavailable. Check local access configuration."
              : response.status === 404
                ? "This session is no longer retained."
                : response.status === 422
                  ? "These filters are not valid. Check the session ID and time range."
                  : "Analytics is temporarily unavailable. Please retry.";
        throw new Error(message);
      }
      return parse(await response.json());
    } catch (error) {
      if (timedOut)
        throw new Error("Analytics request timed out. Please retry.");
      if (controller.signal.aborted)
        throw new DOMException("Request cancelled", "AbortError");
      if (error instanceof SyntaxError)
        throw new Error(
          "Analytics returned an invalid response. Check the same-origin proxy.",
        );
      if (error instanceof TypeError)
        throw new Error(
          "Cannot reach analytics. Check the backend and local proxy.",
        );
      throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener("abort", cancel);
    }
  }
  overview(filters: Filters = {}, signal?: AbortSignal) {
    return this.request("overview", parseOverview, filters, signal);
  }
  sessions(filters: Filters = {}, signal?: AbortSignal) {
    return this.request("sessions", parseSessionPage, filters, signal);
  }
  detail(id: string, signal?: AbortSignal, filters: Filters = {}) {
    return this.request(
      `sessions/${encodeURIComponent(id)}/detail`,
      parseDetail,
      filters,
      signal,
    );
  }
  journey(id: string, signal?: AbortSignal, filters: Filters = {}) {
    return this.request(
      `sessions/${encodeURIComponent(id)}/journey`,
      parseJourneyPage,
      filters,
      signal,
    );
  }
  anomalies(
    filters: Pick<
      Filters,
      "channel" | "scenario" | "source" | "as_of" | "limit" | "offset"
    > = {},
    signal?: AbortSignal,
  ) {
    return this.request("anomalies", parseAnomalyPage, filters, signal);
  }
  scenarios(filters: Filters = {}, signal?: AbortSignal) {
    return this.request("scenarios", ranked, filters, signal);
  }
  risk(filters: Filters = {}, signal?: AbortSignal) {
    return this.request("risk", parseRisk, filters, signal);
  }
}
