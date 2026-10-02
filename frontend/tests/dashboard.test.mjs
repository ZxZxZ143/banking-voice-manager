import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  parseAnomalies,
  parseDetail,
  parseOverview,
  parseRisk,
  parseSessions,
} from "../src/analytics/parse.ts";
import {
  OverviewView,
  LiveCallCards,
  AnomalyCards,
  RiskView,
} from "../src/components/dashboard/views.tsx";
import { SessionTable } from "../src/components/dashboard/SessionTable.tsx";
import { DetailContent } from "../src/components/dashboard/SessionDetail.tsx";
import { Journey } from "../src/components/dashboard/Journey.tsx";
import {
  DataState,
  DemoBadge,
  RiskBadge,
} from "../src/components/dashboard/shared.tsx";
import { demoScope } from "../src/components/dashboard/presentation.ts";

const render = (Component, props = {}) =>
  renderToStaticMarkup(React.createElement(Component, props));
const sessions = parseSessions([
  {
    session_id: "DEMO-phone",
    channel: "phone",
    status: "awaiting_user",
    active: true,
    risk_level: "high",
    risk_signals: ["DEMO_SIGNAL"],
    last_scenario: "CARD_BLOCK",
    turn_count: 2,
    provider_metadata: { provider: "demo", call_uuid: "DEMO-uuid", demo: true },
    latest_latency: { agent_ms: 3000, tts_ms: 2000 },
  },
]);
const overview = parseOverview({
  total_sessions: 38,
  active_sessions: 1,
  sessions_by_channel: { phone: 37, web: 1 },
  risk: { high_risk_sessions: 12 },
  latency: {
    agent_ms: { average_ms: 3000, samples: 12 },
    tts_ms: { average_ms: 2000, samples: 12 },
  },
});
const select = () => {};

test("overview renders API metrics and honest unavailable measurements", () => {
  const html = render(OverviewView, {
    data: overview,
    anomalies: [],
    sessions,
    onSelect: select,
  });
  for (const text of [
    "Total sessions",
    "38",
    "Phone sessions",
    "37",
    "High risk signals",
    "12",
    "3.00 s",
    "2.00 s",
    "Recent conversations",
  ])
    assert.ok(html.includes(text), text);
  assert.ok(html.includes("—"));
});
test("overview empty state uses zero data without fixture fallback", () => {
  const html = render(OverviewView, {
    data: parseOverview({ total_sessions: 0 }),
    anomalies: [],
    sessions: [],
    onSelect: select,
  });
  assert.ok(html.includes("No conversations yet"));
  assert.ok(!html.includes("DEMO-phone"));
});
test("loading skeleton has an accessible status", () => {
  const html = render(DataState, {
    resource: { data: null, loading: true, error: null, updatedAt: null },
    retry() {},
    children() {
      assert.fail();
    },
  });
  assert.ok(html.includes("Loading analytics"));
  assert.ok(html.includes('role="status"'));
});
test("error state exposes retry and labels stale previously loaded data", () => {
  const html = render(DataState, {
    resource: {
      data: [],
      loading: false,
      error: "Connection unavailable",
      updatedAt: 1,
    },
    retry() {},
    children() {
      return "Previous sessions";
    },
  });
  assert.ok(html.includes("showing previous data"));
  assert.ok(html.includes("Retry"));
  assert.ok(html.includes("Previous sessions"));
});
test("live calls render phone provider, identity, state, risk, timing and detail action", () => {
  const html = render(LiveCallCards, { sessions, onSelect: select });
  for (const text of [
    "DEMO-uuid",
    "DEMO-phone",
    "High risk signal",
    "awaiting user",
    "CARD BLOCK",
    "3.00 s",
    "2.00 s",
    "Inspect call session",
  ])
    assert.ok(html.includes(text), text);
});
test("session table has a keyboard-accessible named detail button", () => {
  const html = render(SessionTable, { sessions, onSelect: select });
  assert.ok(html.includes('aria-label="Open session DEMO-phone"'));
  assert.ok(html.includes("<table"));
  assert.ok(html.includes("Phone"));
});
test("unknown risk is displayed as no data and not low risk", () => {
  const html = render(RiskBadge, { level: "unknown" });
  assert.ok(html.includes("No risk data"));
  assert.ok(!html.includes("Low signal"));
});
test("session detail renders clarification, handoff and latency fields safely", () => {
  const detail = parseDetail({
    summary: { ...sessions[0], handoff: true, clarification_count: 1 },
  });
  const html = render(DetailContent, { detail });
  assert.ok(html.includes("Operator attention requested"));
  assert.ok(html.includes("Clarifications"));
  assert.ok(html.includes("Average Agent"));
  assert.ok(html.includes("3.00 s") === false); // latest timing is not invented as an average
});
test("journey preserves actual scenario order and explicit lifecycle markers", () => {
  const detail = parseDetail({
    summary: sessions[0],
    journey: [
      { id: "a", channel: "phone", scenario: "LOGIN_PROBLEM" },
      { id: "b", channel: "phone", scenario: "SUSPICIOUS_TRANSACTION" },
      { id: "c", channel: "phone", scenario: "CARD_BLOCK" },
      { id: "d", channel: "phone", handoff: true },
    ],
  });
  const html = render(Journey, { stages: detail.journey });
  assert.ok(
    html.indexOf("LOGIN PROBLEM") < html.indexOf("SUSPICIOUS TRANSACTION"),
  );
  assert.ok(
    html.indexOf("SUSPICIOUS TRANSACTION") < html.indexOf("CARD BLOCK"),
  );
  assert.ok(html.includes("Handoff"));
});
test("anomalies render current/baseline/ratio/window/explanation with safe wording", () => {
  const anomalies = parseAnomalies([
    {
      key: "FRAUD_CALL_REPORT",
      metric: "scenario",
      current_count: 12,
      baseline_count: 24,
      baseline_expected_count: 4,
      ratio: 3,
      severity: "low",
      explanation: "Observed abnormal increase. Review underlying events.",
      window: {
        current_from: "2026-10-02T11:00:00Z",
        current_to: "2026-10-02T12:00:00Z",
      },
    },
  ]);
  const html = render(AnomalyCards, { anomalies });
  for (const text of [
    "12",
    "24",
    "3.0×",
    "Expected per equivalent window",
    "abnormal increase",
    "Current:",
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(
    html.toLowerCase(),
    /confirmed attack|fraud confirmed|fraud campaign confirmed/,
  );
});
test("risk aggregation uses AI-generated signal language and preserves unknown counts", () => {
  const html = render(RiskView, {
    data: parseRisk({
      levels: { unknown: 2, low: 24, high: 12 },
      high_risk_sessions: 12,
    }),
    sessions,
    onSelect: select,
  });
  assert.ok(html.includes("AI-generated risk signals"));
  assert.ok(html.includes("No risk data"));
  assert.ok(html.includes("12 total"));
  assert.doesNotMatch(html.toLowerCase(), /fraud confirmed|confirmed attack/);
});
test("demo and mixed datasets are explicitly labelled", () => {
  assert.equal(demoScope(sessions), "demo");
  assert.equal(
    demoScope([
      ...sessions,
      ...parseSessions([{ session_id: "real-id", channel: "web" }]),
    ]),
    "mixed",
  );
  assert.ok(render(DemoBadge).includes("DEMO DATA"));
  assert.ok(render(DemoBadge, { mixed: true }).includes("DEMO + REAL DATA"));
});
test("backend transcript text is escaped rather than interpreted as markup", () => {
  const detail = parseDetail({
    summary: sessions[0],
    timeline: [
      {
        id: "x",
        event_type: "agent.response",
        text: "<script>PRIVATE</script>",
      },
    ],
  });
  const html = render(DetailContent, { detail, initialTab: "timeline" });
  assert.ok(html.includes("&lt;script&gt;PRIVATE&lt;/script&gt;"));
  assert.ok(!html.includes("<script>"));
});
