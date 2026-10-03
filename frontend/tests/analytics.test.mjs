import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { AnalyticsClient } from "../src/analytics/client.ts";
import {
  parseOverview,
  parseSessionPage,
  parseDetail,
  parseJourneyPage,
  parseAnomalyPage,
  parseRisk,
} from "../src/analytics/parse.ts";
import { startPolling } from "../src/analytics/polling.ts";
const fixtures = JSON.parse(
  readFileSync(new URL("./dashboard-fixtures.json", import.meta.url), "utf8"),
);
const json = (value) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  });
const next = () => new Promise((resolve) => setTimeout(resolve, 0));
test("persisted overview parses aggregate totals and unavailable latency", () => {
  const data = parseOverview({ ...fixtures.overview, future_addition: true });
  assert.equal(data.total_sessions, 144);
  assert.deepEqual(data.sessions_by_channel, { text: 60, voice: 84 });
  assert.equal(data.latency.agent_ms.average_ms, null);
  assert.equal(data.insurance_completed, 24);
});
test("required malformed fields fail instead of fabricated zero or source", () => {
  assert.throws(() => parseOverview({}), /required count/);
  assert.throws(
    () => parseSessionPage({ ...fixtures.sessions, sessions: [{}] }),
    /identifier/,
  );
  for (const bad of [
    { channel: "phone" },
    { risk_level: "confirmed_fraud" },
    { source: "DEMO" },
  ])
    assert.throws(() =>
      parseSessionPage({
        ...fixtures.sessions,
        sessions: [{ ...fixtures.sessions.sessions[0], ...bad }],
      }),
    );
  assert.throws(() =>
    parseAnomalyPage({ ...fixtures.anomalies, history_status: "unknown" }),
  );
});
test("safe persisted detail excludes unsafe additive fields", () => {
  const data = structuredClone(fixtures.detail);
  data.timeline[0].text = "PRIVATE_TRANSCRIPT";
  data.timeline[0].payload.password = "PRIVATE_SECRET";
  const parsed = parseDetail(data);
  assert.doesNotMatch(JSON.stringify(parsed), /PRIVATE/);
  assert.equal(parsed.summary.results[0].payload.campaign, "card");
});
test("bounded journey preserves backend order and anomaly source", () => {
  const page = parseJourneyPage(fixtures.journey);
  assert.equal(page.stages[0].event_type, "conversation_started");
  assert.equal(page.stages.at(-1).event_type, "operator_handoff");
  assert.equal(
    parseAnomalyPage(fixtures.anomalies).anomalies[0].source,
    "synthetic_demo",
  );
  assert.equal(parseRisk(fixtures.risk).high_risk_sessions, 64);
});
test("client uses same-origin additive contract, pagination, source and assistant filters", async () => {
  const calls = [];
  const client = new AnalyticsClient(
    async (url, options) => {
      calls.push({ url, options });
      return json(fixtures.sessions);
    },
    12000,
    "runtime",
  );
  await client.sessions({
    channel: "voice",
    scenario: "card_promoter",
    session_id: "a & b",
    limit: 20,
    offset: 100,
  });
  assert.equal(
    calls[0].url,
    "/api/analytics/sessions?source=runtime&channel=voice&assistant_id=card_promoter&session_id=a+%26+b&limit=20&offset=100",
  );
  assert.deepEqual(calls[0].options.headers, { Accept: "application/json" });
  assert.equal(calls[0].options.method, "GET");
  const details = new AnalyticsClient(async (url) => {
    calls.push({ url });
    return json(fixtures.detail);
  });
  await details.detail("a & b");
  assert.equal(calls[1].url, "/api/analytics/sessions/a%20%26%20b/detail");
});
test("all seven methods parse the final typed contract", async () => {
  const client = new AnalyticsClient(async (url) => {
    if (url.endsWith("/journey")) return json(fixtures.journey);
    if (url.endsWith("/detail")) return json(fixtures.detail);
    if (url.includes("/sessions")) return json(fixtures.sessions);
    if (url.includes("/anomalies")) return json(fixtures.anomalies);
    if (url.includes("/risk")) return json(fixtures.risk);
    if (url.includes("/scenarios"))
      return json(fixtures.overview.sessions_by_scenario);
    return json(fixtures.overview);
  });
  await client.overview();
  await client.sessions();
  await client.detail("x");
  await client.journey("x");
  await client.scenarios();
  await client.risk();
  await client.anomalies();
});
for (const [status, message] of [
  [503, /storage is unavailable/],
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
test("bundle-facing dashboard source has no analytics token, browser storage or server imports", () => {
  function walk(path) {
    return readdirSync(path, { withFileTypes: true }).flatMap((entry) =>
      entry.isDirectory()
        ? walk(`${path}/${entry.name}`)
        : [`${path}/${entry.name}`],
    );
  }
  const paths = [
    ...walk(fileURLToPath(new URL("../src/analytics", import.meta.url))),
    ...walk(
      fileURLToPath(new URL("../src/components/dashboard", import.meta.url)),
    ),
    fileURLToPath(new URL("../src/App.tsx", import.meta.url)),
  ];
  for (const path of paths)
    assert.doesNotMatch(
      readFileSync(path, "utf8"),
      /ANALYTICS_API_TOKEN|localStorage|server\/analyticsProxy/,
    );
});
