import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  parseOverview,
  parseRisk,
  parseSessionPage,
  parseDetail,
  parseAnomalyPage,
} from "../src/analytics/parse.ts";
import {
  OverviewView,
  LiveCallCards,
  AnomalyCards,
  RiskView,
  Pager,
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
const fixtures = JSON.parse(
  readFileSync(new URL("./dashboard-fixtures.json", import.meta.url), "utf8"),
);
const render = (Component, props = {}) =>
  renderToStaticMarkup(React.createElement(Component, props));
const sessions = parseSessionPage(fixtures.sessions).sessions;
const detail = parseDetail(fixtures.detail);
const select = () => {};
test("overview shows real aggregate counts, sales, insurance and unavailable measurements", () => {
  const html = render(OverviewView, {
    data: parseOverview(fixtures.overview),
    anomalies: [],
    sessions,
    onSelect: select,
  });
  for (const text of [
    "Total sessions",
    "144",
    "Voice sessions",
    "Text sessions",
    "High risk signals",
    "Sales outcomes",
    "Insurance completed",
    "Recent conversations",
    "—",
  ])
    assert.ok(html.includes(text), text);
});
test("empty overview has no synthetic fallback", () => {
  const empty = {
    ...fixtures.overview,
    total_sessions: 0,
    sessions_by_channel: { text: 0, voice: 0 },
    sales_outcomes: [],
    insurance_completed: 0,
  };
  const html = render(OverviewView, {
    data: parseOverview(empty),
    anomalies: [],
    sessions: [],
    onSelect: select,
  });
  assert.ok(html.includes("No conversations yet"));
  assert.ok(!html.includes("synthetic-demo"));
});
test("loading has accessible status", () => {
  const html = render(DataState, {
    resource: { data: null, loading: true, error: null, updatedAt: null },
    retry() {},
    children() {
      assert.fail();
    },
  });
  assert.ok(html.includes('role="status"'));
  assert.ok(html.includes("Loading analytics"));
});
test("storage error retains and explicitly labels stale data", () => {
  const html = render(DataState, {
    resource: {
      data: [],
      loading: false,
      error: "Analytics storage is unavailable",
      updatedAt: 1,
    },
    retry() {},
    children() {
      return "Previous sessions";
    },
  });
  for (const text of [
    "showing previous data",
    "Retry",
    "Previous sessions",
    "storage is unavailable",
  ])
    assert.ok(html.includes(text));
});
test("live view shows persisted voice session without provider metadata", () => {
  const html = render(LiveCallCards, { sessions, onSelect: select });
  for (const text of [
    "Voice session",
    "synthetic_demo",
    "High risk signal",
    "Inspect call session",
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Vonage|PSTN call|Phone provider|call_uuid/);
});
test("session list offers accessible detail action and explicit demo badge", () => {
  const html = render(SessionTable, { sessions, onSelect: select });
  assert.ok(
    html.includes(`aria-label="Open session ${sessions[0].session_id}"`),
  );
  assert.ok(html.includes("DEMO DATA"));
  assert.ok(html.includes("Voice"));
});
test("risk none and unknown remain distinct advisory states", () => {
  assert.ok(render(RiskBadge, { level: "unknown" }).includes("No risk data"));
  assert.ok(
    render(RiskBadge, { level: "none" }).includes("No observed signal"),
  );
  const html = render(RiskView, {
    data: parseRisk(fixtures.risk),
    sessions,
    onSelect: select,
  });
  assert.ok(html.includes("AI-generated risk signals"));
  assert.ok(html.includes("Advisory case types"));
  assert.doesNotMatch(html.toLowerCase(), /confirmed fraud|confirmed attack/);
});
test("session detail displays persisted sales result and safe insurance fields", () => {
  const html = render(DetailContent, { detail });
  for (const text of [
    "sales lead",
    "CARD-DAILY",
    "campaign",
    "card",
    "interest level",
    "next action",
    "Persisted business results",
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /Provider correlation|PRIVATE/);
});
test("journey renders original lifecycle order and handoff", () => {
  const html = render(Journey, { stages: fixtures.journey.stages });
  assert.ok(html.indexOf("conversation started") < html.indexOf("fraud case"));
  assert.ok(html.includes("operator handoff"));
});
test("anomalies show persisted baseline and safe explanation", () => {
  const html = render(AnomalyCards, {
    anomalies: parseAnomalyPage(fixtures.anomalies).anomalies,
  });
  for (const text of [
    "18.0×",
    "Expected per equivalent window",
    "anomalous increase",
    "Cause is not established",
    "synthetic_demo",
    "Current:",
  ])
    assert.ok(html.includes(text), text);
  assert.doesNotMatch(html.toLowerCase(), /confirmed attack|fraud confirmed/);
});
test("source identity is explicit, never inferred from session ID", () => {
  assert.equal(demoScope(sessions), "demo");
  assert.equal(
    demoScope([
      ...sessions,
      { ...sessions[0], source: "runtime", session_id: "DEMO-runtime" },
    ]),
    "mixed",
  );
  assert.equal(
    demoScope([
      { ...sessions[0], source: "runtime", session_id: "DEMO-runtime" },
    ]),
    "none",
  );
  assert.ok(render(DemoBadge, { mixed: true }).includes("DEMO + REAL DATA"));
});
test("timeline rejects raw transcript and escapes safe labels", () => {
  const raw = structuredClone(fixtures.detail);
  raw.timeline[0].text = "PRIVATE_TRANSCRIPT";
  raw.timeline[0].payload.password = "PRIVATE_SECRET";
  const html = render(DetailContent, {
    detail: parseDetail(raw),
    initialTab: "timeline",
  });
  assert.doesNotMatch(html, /PRIVATE/);
  assert.ok(html.includes("conversation_started"));
});
test("pagination has explicit totals and bounded next/previous actions", () => {
  const html = render(Pager, { page: fixtures.sessions, change() {} });
  assert.ok(html.includes("144 total"));
  assert.ok(html.includes("Next page"));
  assert.ok(html.includes("Previous page"));
});
test("all dashboard sections and source filter remain in the shell", () => {
  const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  for (const section of [
    "Overview",
    "Live Calls",
    "Sessions",
    "Risk & Fraud",
    "Anomalies",
    "Journeys",
    "Conversation Demo",
    "Source filter",
  ])
    assert.ok(app.includes(section), section);
  assert.ok(app.includes('hidden={section !== "conversation"}'));
  assert.ok(app.includes("useState("));
  const demo = readFileSync(
    new URL(
      "../src/components/dashboard/ConversationDemo.tsx",
      import.meta.url,
    ),
    "utf8",
  );
  assert.ok(demo.includes("snapshot.lastResponse?.risk"));
  assert.ok(demo.includes("TtsDebugPanel"));
});
