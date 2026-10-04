/** Real Conversation Demo/audio/WS with live RT/TTS and explicit server fault injection.
 * Results contain counters, statuses and monotonic timings, never segment content.
 */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = new URL("../work/segment-capture/", import.meta.url);
await mkdir(root, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
});
const results = [];
try {
  for (const caseId of (
    process.env.SEGMENT_CASES || "single,dual,disagreement,keyboard,iin"
  ).split(",")) {
    const page = await context.newPage();
    let sessionId,
      response,
      count = 0,
      activeCount = 0;
    const result = {
      case: caseId,
      mode: "live RT/TTS with explicit ASR fault injection",
      microphone: "synthetic MediaStream",
      turns: [],
    };
    await page.addInitScript(() => {
      const fixture = {
        timings: [],
        active: 0,
        destinations: [],
        tracks: [],
        context: null,
      };
      window.__segmentGate = fixture;
      window.addEventListener("voice-timing", ({ detail }) => {
        fixture.timings.push(detail);
        if (detail.event === "input.active") fixture.active++;
      });
      navigator.mediaDevices.getUserMedia = async () => {
        fixture.context ??= new AudioContext({ sampleRate: 24000 });
        await fixture.context.resume();
        const destination = fixture.context.createMediaStreamDestination();
        fixture.destinations.push(destination);
        fixture.tracks.push(...destination.stream.getTracks());
        return destination.stream;
      };
      fixture.play = async (name) => {
        const bytes = await (
          await fetch("/segment/audio/" + name)
        ).arrayBuffer();
        const source = fixture.context.createBufferSource();
        source.buffer = await fixture.context.decodeAudioData(bytes);
        fixture.destinations
          .filter((d) =>
            d.stream.getTracks().some((t) => t.readyState === "live"),
          )
          .forEach((d) => source.connect(d));
        source.start();
      };
      const Native = window.WebSocket;
      window.WebSocket = new Proxy(Native, {
        construct(Target, args) {
          args[0] = "ws://127.0.0.1:8015/api/v1/voice";
          return Reflect.construct(Target, args);
        },
      });
    });
    await page.route(/\/(api|segment)\//, async (route) => {
      const url = new URL(route.request().url());
      const fetched = await route.fetch({
        url: "http://127.0.0.1:8015" + url.pathname + url.search,
        timeout: 90000,
      });
      if (url.pathname === "/api/conversation/start") {
        const initial = await fetched.json();
        sessionId = initial.session_id;
        const seed = await (
          await context.request.post(
            `http://127.0.0.1:8015/segment/seed/${caseId}/${sessionId}`,
          )
        ).json();
        await route.fulfill({
          response: fetched,
          json: { ...initial, response_text: seed.response_text },
        });
      } else {
        if (url.pathname === "/api/message") {
          response = await fetched.json();
          count++;
        }
        await route.fulfill({ response: fetched });
      }
    });
    const check = async () =>
      await (
        await context.request.get(
          `http://127.0.0.1:8015/segment/check/${sessionId}`,
        )
      ).json();
    async function say(
      name,
      expectedPhase,
      expectedDrafts,
      final = false,
      allowSingle = false,
      retryConfirmation = true,
    ) {
      await page.waitForFunction(
        (n) => window.__segmentGate.active > n,
        activeCount,
        { timeout: 90000 },
      );
      activeCount = await page.evaluate(() => window.__segmentGate.active);
      const before = count;
      const started = Date.now();
      await page.evaluate((name) => window.__segmentGate.play(name), name);
      while (count === before && Date.now() - started < 90000)
        await page.waitForTimeout(100);
      assert.equal(
        count,
        before + 1,
        "one voice turn must produce exactly one reply",
      );
      const snapshot = await check();
      result.turns.push({
        phase: snapshot.phase,
        drafts: snapshot.draft_count,
        attempts: snapshot.attempts,
        status: response.conversation_status,
        recognition: response.trace?.recognition,
      });
      assert.notEqual(
        response.conversation_status,
        "handoff",
        "no early handoff",
      );
      if (!final) {
        assert.equal(snapshot.lookups, 0);
        assert.equal(snapshot.accepted_expected, false);
        assert.equal(response.trace.recognition.accepted, false);
        assert.deepEqual(response.trace.actions, []);
        if (allowSingle && snapshot.phase === "segment_confirmation") {
          assert.equal(snapshot.draft_count, expectedDrafts - 1);
          assert.equal(
            snapshot.segment_matches,
            true,
            "customer confirms only the correct fixture part",
          );
          assert.equal(response.trace.recognition.segment_evidence, "single");
          return await say("yes", expectedPhase, expectedDrafts);
        }
        assert.equal(snapshot.phase, expectedPhase);
        assert.equal(snapshot.draft_count, expectedDrafts);
      } else {
        if (!snapshot.accepted_expected && retryConfirmation) {
          assert.equal(snapshot.phase, "confirmation");
          assert.equal(snapshot.source_preserved, true);
          assert.equal(snapshot.lookups, 0);
          assert.deepEqual(response.trace.actions, []);
          result.finalConfirmationRetried = true;
          return await say("yes", null, 0, true, false, false);
        }
        assert.equal(snapshot.accepted_expected, true);
      }
      return snapshot;
    }
    try {
      await page.goto("http://127.0.0.1:5173");
      await page
        .getByRole("button", { name: "Conversation Demo", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Начать разговор", exact: true })
        .click();
      await say("whole", "segments", 0);
      if (caseId === "single") {
        await say("first", "segment_confirmation", 0);
        result.firstSegmentReadback = response.response_text.startsWith(
          "Я услышал: восемь, семь, семь, семь",
        );
        assert.equal(result.firstSegmentReadback, true);
        await say("yes", "segments", 1);
      } else if (caseId === "dual") {
        await say("first", "segments", 1);
      } else if (caseId === "iin") {
        await say("iin_first", "segments", 1, false, true);
      } else {
        await say("first", "segments", 0);
        assert.match(response.response_text, /Повторите.*первые 4/);
        if (caseId === "keyboard") {
          const snapshot = await say("first", "segments", 0);
          assert.equal(snapshot.manual, true);
          assert.equal(response.trace.recognition.outcome, "manual_fallback");
          await page
            .getByLabel("Текст клиента (отладочный ввод)")
            .fill("87775232862", { timeout: 90000 });
          const before = count;
          await page
            .getByRole("button", { name: "Отправить", exact: true })
            .click();
          const deadline = Date.now() + 90000;
          while (count === before && Date.now() < deadline)
            await page.waitForTimeout(100);
          assert.equal((await check()).accepted_expected, true);
          assert.equal(
            response.trace.recognition.verification_method,
            "manual_entry",
          );
          result.pass = true;
          continue;
        }
        await say("first", "segments", 1);
      }
      if (caseId !== "iin") await say("middle", "segments", 2, false, true);
      const assembled = await say(
        caseId === "iin" ? "iin_last" : "last",
        "confirmation",
        caseId === "iin" ? 2 : 3,
        false,
        true,
      );
      assert.equal(assembled.source_preserved, true);
      assert.match(
        response.response_text,
        caseId === "iin"
          ? /Проверьте номер: один, два/
          : /Проверьте номер: восемь, семь, семь, семь/,
      );
      result.fullReadbackPreserved = true;
      await page.screenshot({
        path: new URL(caseId + "-full-readback.png", root).pathname.slice(1),
        fullPage: true,
      });
      await say("yes", null, 0, true);
      result.pass = true;
    } catch (error) {
      result.pass = false;
      result.failure = error.message;
      result.alerts = await page.getByRole("alert").allTextContents();
      await page.screenshot({
        path: new URL(caseId + "-failed.png", root).pathname.slice(1),
        fullPage: true,
      });
    } finally {
      result.check = await check().catch(() => null);
      result.timings = await page.evaluate(() => window.__segmentGate.timings);
      await page
        .getByRole("button", { name: "Завершить", exact: true })
        .click({ timeout: 3000 })
        .catch(() => {});
      result.tracksStopped = await page.evaluate(() =>
        window.__segmentGate.tracks.every((t) => t.readyState === "ended"),
      );
      if (!result.tracksStopped) result.pass = false;
      results.push(result);
      await writeFile(
        new URL("browser-results.json", root),
        JSON.stringify(results, null, 2),
      );
      console.log(
        JSON.stringify({
          case: caseId,
          pass: result.pass,
          failure: result.failure,
          tracksStopped: result.tracksStopped,
        }),
      );
      await page.unrouteAll({ behavior: "ignoreErrors" });
      await page.close();
    }
  }
} finally {
  await browser.close();
}
if (results.some((r) => !r.pass)) process.exitCode = 1;
