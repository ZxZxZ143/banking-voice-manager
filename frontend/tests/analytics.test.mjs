import assert from "node:assert/strict";
import { test } from "node:test";
import { readdirSync, readFileSync } from "node:fs";
import { AnalyticsClient } from "../src/analytics/client.ts";
import {
  parseAnomalies,
  parseDetail,
  parseJourney,
  parseOverview,
  parseRisk,
  parseSessions,
} from "../src/analytics/parse.ts";
import { startPolling } from "../src/analytics/polling.ts";
import { allowedRequest, analyticsProxy } from "../server/analyticsProxy.ts";

const next = () => new Promise((resolve) => setImmediate(resolve));
const json = (value) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });

test("overview parsing preserves measured values and distinct latency semantics", () => {
  const parsed = parseOverview({
    total_sessions: 38,
    sessions_by_channel: { phone: 37, web: 1 },
    latency: {
      agent_ms: { average_ms: 3000, samples: 12 },
      speech_end_to_playback_submit_ms: { average_ms: 6400, samples: 12 },
      speech_end_to_playback_complete_ms: { average_ms: 7400, samples: 12 },
    },
  });
  assert.equal(parsed.total_sessions, 38);
  assert.deepEqual(parsed.sessions_by_channel, { phone: 37, web: 1 });
  assert.equal(parsed.latency.agent_ms.average_ms, 3000);
  assert.notEqual(
    parsed.latency.speech_end_to_playback_submit_ms.average_ms,
    parsed.latency.speech_end_to_playback_complete_ms.average_ms,
  );
});
test("partial metrics remain unavailable rather than fabricated zero", () => {
  const parsed = parseOverview({ latency: { agent_ms: { average_ms: -1 } } });
  assert.equal(parsed.total_sessions, null);
  assert.equal(parsed.risk.levels.low, null);
  assert.equal(parsed.latency.agent_ms.average_ms, null);
  assert.deepEqual(parseSessions(null), []);
});
test("sessions preserve phone identity and ignore untrusted metadata keys", () => {
  const [session] = parseSessions([
    {
      session_id: "DEMO-phone",
      channel: "phone",
      risk_level: "high",
      provider_metadata: {
        provider: "demo",
        call_uuid: "DEMO-uuid",
        demo: true,
        authorization: "DO_NOT_DISPLAY",
        private_key: "DO_NOT_DISPLAY",
      },
    },
  ]);
  assert.equal(session.risk_level, "high");
  assert.deepEqual(session.provider_metadata, {
    provider: "demo",
    call_uuid: "DEMO-uuid",
    demo: true,
  });
});
test("missing risk is unknown, unsupported channels are rejected", () => {
  assert.equal(
    parseSessions([{ session_id: "DEMO", channel: "web" }])[0].risk_level,
    "unknown",
  );
  assert.throws(
    () => parseSessions([{ session_id: "DEMO", channel: "mobile" }]),
    /invalid channel/,
  );
  assert.throws(() => parseSessions([{}]), /identifier/);
});
test("detail, journey and anomalies tolerate missing optional fields and preserve order", () => {
  const stages = parseJourney([
    { id: "first", channel: "phone", scenario: "LOGIN_PROBLEM" },
    { id: "second", channel: "phone", handoff: true },
  ]);
  assert.deepEqual(
    stages.map((s) => s.id),
    ["first", "second"],
  );
  assert.equal(stages[1].handoff, true);
  assert.deepEqual(
    parseDetail({ summary: { session_id: "DEMO", channel: "web" } }).timeline,
    [],
  );
  assert.equal(parseAnomalies([{}])[0].severity, "unknown");
  assert.equal(parseRisk({}).high_risk_sessions, null);
});
test("typed client uses same-origin GET routes, encodes IDs and never sends credentials", async () => {
  const calls = [];
  const client = new AnalyticsClient(async (url, options) => {
    calls.push({ url, options });
    return json([{ session_id: "DEMO", channel: "phone" }]);
  });
  await client.sessions({
    channel: "phone",
    active: true,
    session_id: "a & b",
    limit: 20,
  });
  assert.equal(
    calls[0].url,
    "/analytics-api/sessions?channel=phone&active=true&session_id=a+%26+b&limit=20",
  );
  assert.deepEqual(calls[0].options.headers, { Accept: "application/json" });
  assert.equal(calls[0].options.method, "GET");
  const details = new AnalyticsClient(async (url) => {
    calls.push({ url });
    return json({ summary: { session_id: "a & b", channel: "web" } });
  });
  await details.detail("a & b");
  assert.equal(calls[1].url, "/analytics-api/sessions/a%20%26%20b");
});
test("all seven client methods parse their endpoint responses", async () => {
  const client = new AnalyticsClient(async (url) => {
    if (url.includes("/sessions/DEMO/journey")) return json([]);
    if (url.includes("/sessions/DEMO"))
      return json({ summary: { session_id: "DEMO", channel: "web" } });
    if (
      url.includes("/sessions") ||
      url.includes("/scenarios") ||
      url.includes("/anomalies")
    )
      return json([]);
    return json({});
  });
  await client.overview();
  await client.sessions();
  await client.detail("DEMO");
  await client.journey("DEMO");
  await client.scenarios();
  await client.risk();
  await client.anomalies();
});
for (const [status, message] of [
  [503, /not configured/],
  [403, /access is unavailable/],
  [404, /no longer retained/],
  [422, /filters/],
  [500, /temporarily unavailable/],
]) {
  test(`HTTP ${status} errors are actionable and do not echo server diagnostic contents`, async () => {
    const client = new AnalyticsClient(
      async () => new Response("PRIVATE_DIAGNOSTIC", { status }),
    );
    await assert.rejects(client.overview(), message);
  });
}
test("invalid JSON and network failures have safe messages", async () => {
  await assert.rejects(
    new AnalyticsClient(
      async () => new Response("<html>SPA</html>"),
    ).overview(),
    /invalid response/,
  );
  await assert.rejects(
    new AnalyticsClient(async () => {
      throw new TypeError("PRIVATE_NETWORK_DETAIL");
    }).overview(),
    /Cannot reach analytics/,
  );
});
test("timeout and parent cancellation abort pending reads", async () => {
  const hang = (_url, options) =>
    new Promise((_resolve, reject) =>
      options.signal.addEventListener(
        "abort",
        () => reject(new DOMException("Aborted", "AbortError")),
        { once: true },
      ),
    );
  await assert.rejects(new AnalyticsClient(hang, 10).overview(), /timed out/);
  const abort = new AbortController();
  const request = new AnalyticsClient(hang).overview({}, abort.signal);
  abort.abort();
  await assert.rejects(request, { name: "AbortError" });
});
test("polling refresh cancels superseded requests and ignores stale results", async () => {
  const requests = [];
  const values = [];
  const handle = startPolling(
    (signal) => new Promise((resolve) => requests.push({ signal, resolve })),
    {
      loading() {},
      data(value) {
        values.push(value);
      },
      error(message) {
        throw new Error(message);
      },
    },
  );
  handle.refresh();
  assert.equal(requests[0].signal.aborted, true);
  requests[0].resolve("stale");
  requests[1].resolve("current");
  await next();
  assert.deepEqual(values, ["current"]);
  handle.stop();
});
test("polling cleanup aborts in-flight calls and prevents later updates", async () => {
  let signal;
  let resolve;
  let updated = false;
  const handle = startPolling(
    (value) => {
      signal = value;
      return new Promise((done) => {
        resolve = done;
      });
    },
    {
      loading() {},
      data() {
        updated = true;
      },
      error() {},
    },
    3000,
  );
  handle.stop();
  assert.equal(signal.aborted, true);
  resolve("late");
  await next();
  assert.equal(updated, false);
});
test("polling never overlaps and skips hidden-page network activity", async () => {
  let requests = 0;
  let done;
  const handle = startPolling(
    () => {
      requests++;
      return new Promise((resolve) => {
        done = resolve;
      });
    },
    { loading() {}, data() {}, error() {} },
    10,
    () => false,
  );
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.equal(requests, 1);
  done([]);
  await new Promise((resolve) => setTimeout(resolve, 30));
  assert.equal(requests, 1);
  handle.stop();
});
test("proxy accepts only local same-origin read-only analytics routes", () => {
  const request = {
    method: "GET",
    url: "/analytics-api/sessions/DEMO/journey",
    headers: { host: "127.0.0.1:5173", origin: "http://127.0.0.1:5173" },
  };
  assert.equal(allowedRequest(request), true);
  for (const bad of [
    { method: "POST" },
    { url: "/analytics-api/../message" },
    { url: "/analytics-api/sessions/%2fsecret" },
    { url: "/analytics-api/sessions/%2e%2e" },
    { headers: { host: "public.example:5173" } },
    { headers: { host: "127.0.0.1:5173", origin: "https://evil.example" } },
    { headers: { host: "127.0.0.1:5173", "sec-fetch-site": "cross-site" } },
  ])
    assert.equal(allowedRequest({ ...request, ...bad }), false);
});
test("proxy injects authorization only server-side and strips authentication response headers", () => {
  const { options } = analyticsProxy("SERVER_ONLY_FIXTURE");
  const hooks = {};
  options.configure({
    on(event, callback) {
      hooks[event] = callback;
    },
  });
  const headers = { authorization: "CLIENT_SPOOF" };
  hooks.proxyReq({
    removeHeader(key) {
      delete headers[key];
    },
    setHeader(key, value) {
      headers[key] = value;
    },
  });
  assert.equal(headers.Authorization, "Bearer SERVER_ONLY_FIXTURE");
  assert.equal(headers.authorization, undefined);
  const response = {
    headers: {
      authorization: "SERVER_ONLY_FIXTURE",
      "proxy-authorization": "PRIVATE",
    },
  };
  hooks.proxyRes(response);
  assert.deepEqual(response.headers, { "cache-control": "no-store" });
  assert.equal(
    options.rewrite("/analytics-api/risk?channel=phone"),
    "/api/v1/analytics/risk?channel=phone",
  );
  assert.throws(
    () => analyticsProxy("fixture", "https://external.example"),
    /loopback/,
  );
});
test("unconfigured proxy fails closed without returning any token", () => {
  let guard;
  analyticsProxy("").plugin.configureServer({
    middlewares: {
      use(fn) {
        guard = fn;
      },
    },
  });
  const response = {
    statusCode: 200,
    body: "",
    setHeader() {},
    end(value) {
      this.body = value;
    },
  };
  guard(
    {
      method: "GET",
      url: "/analytics-api/overview",
      headers: { host: "localhost:5173" },
    },
    response,
    () => assert.fail("must not forward"),
  );
  assert.equal(response.statusCode, 503);
  assert.match(response.body, /not configured/);
});
test("bundle-facing dashboard source has no analytics token, browser storage or server imports", () => {
  function walk(path) {
    return readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
      entry.isDirectory()
        ? walk(`${path}/${entry.name}`)
        : [`${path}/${entry.name}`],
    );
  }
  const paths = [
    ...walk(new URL("../src/analytics", import.meta.url).pathname),
    ...walk(new URL("../src/components/dashboard", import.meta.url).pathname),
    new URL("../src/App.tsx", import.meta.url).pathname,
  ];
  for (const path of paths)
    assert.doesNotMatch(
      readFileSync(path, "utf8"),
      /ANALYTICS_API_TOKEN|localStorage|server\/analyticsProxy/,
    );
});
