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
import { DemoPeriodNotice } from "../src/components/dashboard/DemoPeriodNotice.tsx";
import { DetailContent } from "../src/components/dashboard/SessionDetail.tsx";
import {
  Journey,
  getJourneyEventIcon,
} from "../src/components/dashboard/Journey.tsx";
import {
  Bot,
  CircleStop,
  Gauge,
  Headphones,
  MessageSquare,
  PlayCircle,
  Route,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
  TriangleAlert,
} from "lucide-react";
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

test("automatic demo period is explicit without implying measured latency", () => {
  const html = render(DemoPeriodNotice, { enabled: true });
  assert.match(html, /Synthetic demo/);
  assert.match(html, /recent 11 hours/);
  assert.match(html, /every 5 minutes/);
  assert.match(html, /Real sessions keep their original dates/);
  assert.match(html, /latency remains unmeasured/);
});

test("runtime-only and disabled views do not claim a synthetic period", () => {
  assert.equal(render(DemoPeriodNotice, { enabled: false }), "");
  assert.equal(
    render(DemoPeriodNotice, { enabled: true, source: "runtime" }),
    "",
  );
  assert.match(
    render(DemoPeriodNotice, { enabled: true, source: "synthetic_demo" }),
    /Synthetic demo/,
  );
});
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

for (const [eventType, Icon] of [
  ["conversation_started", PlayCircle],
  ["assistant_selected", Bot],
  ["conversation_turn", MessageSquare],
  ["insurance_result", ShieldCheck],
  ["sales_lead", TrendingUp],
  ["risk_signal", TriangleAlert],
  ["fraud_case", ShieldAlert],
  ["operator_handoff", Headphones],
  ["conversation_ended", CircleStop],
  ["performance_sample", Gauge],
]) {
  test(`journey ${eventType} renders its semantic decorative icon`, () => {
    assert.equal(getJourneyEventIcon(eventType), Icon);
    const stage = { ...fixtures.journey.stages[0], event_type: eventType };
    const html = render(Journey, { stages: [stage] });
    assert.ok(
      html.includes(
        render(Icon, { className: "size-4", "aria-hidden": "true" }),
      ),
    );
    assert.ok(html.includes(eventType.replaceAll("_", " ")));
  });
}

test("unknown journey event types safely retain the default icon", () => {
  for (const eventType of ["future_event", "constructor", "", "__proto__"]) {
    assert.equal(getJourneyEventIcon(eventType), Route);
    const stage = { ...fixtures.journey.stages[0], event_type: eventType };
    assert.ok(
      render(Journey, { stages: [stage] }).includes(
        render(Route, { className: "size-4", "aria-hidden": "true" }),
      ),
    );
  }
});

test("semantic journey icons preserve labels, action content, ordering and input data", () => {
  const stages = structuredClone(fixtures.journey.stages);
  const before = structuredClone(stages);
  const html = render(Journey, { stages });
  const labels = [...html.matchAll(/<h3[^>]*>(.*?)<\/h3>/g)].map(
    (match) => match[1],
  );
  assert.deepEqual(
    labels,
    stages.map((stage) => stage.event_type.replaceAll("_", " ")),
  );
  assert.ok(
    html.includes("social_engineering · needs_review · operator_handoff"),
  );
  assert.ok(html.includes("Handoff"));
  assert.deepEqual(stages, before);
  assert.notEqual(
    getJourneyEventIcon("conversation_started"),
    getJourneyEventIcon("assistant_selected"),
  );
  assert.notEqual(
    getJourneyEventIcon("assistant_selected"),
    getJourneyEventIcon("insurance_result"),
  );
});
