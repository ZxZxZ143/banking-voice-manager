/** Actual Conversation Demo; synthetic microphone, live TTS/STT and labeled faults. */
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = new URL("../work/confirmation-stt/", import.meta.url);
await mkdir(root, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
});
const results = [];
try {
  for (const caseId of (
    process.env.CONFIRMATION_CASES ||
    "live_ru_yes,live_ru_no,live_kk_yes,live_kk_no,recover_ru_yes,fixture_ru_yes,fixture_unresolved,fixture_kk_yes,fixture_kk_no"
  ).split(",")) {
    const page = await context.newPage();
    let sessionId,
      response,
      count = 0;
    const result = {
      case: caseId,
      microphone: "synthetic MediaStream",
      fixture: !caseId.startsWith("live_"),
      errors: [],
    };
    page.on("pageerror", (e) => result.errors.push(e.name));
    await page.addInitScript(() => {
      const fixture = {
        active: 0,
        tracks: [],
        destinations: [],
        context: null,
        finals: [],
      };
      window.__confirmationGate = fixture;
      window.addEventListener("voice-timing", ({ detail }) => {
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
          await fetch("/confirmation/audio/" + name)
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
          args[0] = "ws://127.0.0.1:8016/api/v1/voice";
          const socket = Reflect.construct(Target, args);
          socket.addEventListener("message", (e) => {
            const event = JSON.parse(e.data);
            if (event.type === "utterance.final") fixture.finals.push(event);
          });
          return socket;
        },
      });
    });
    await page.route(/\/(api|confirmation)\//, async (route) => {
      const url = new URL(route.request().url());
      const fetched = await route.fetch({
        url: "http://127.0.0.1:8016" + url.pathname + url.search,
        timeout: 60000,
      });
      if (url.pathname === "/api/conversation/start") {
        const initial = await fetched.json();
        sessionId = initial.session_id;
        const seed = await (
          await context.request.post(
            `http://127.0.0.1:8016/confirmation/seed/${caseId}/${sessionId}`,
          )
        ).json();
        await route.fulfill({
          response: fetched,
          json: {
            ...initial,
            response_text: seed.response_text,
            state: { ...initial.state, response_language: seed.language },
            routing: {
              ...initial.routing,
              response_language: seed.language,
              language: seed.language,
            },
          },
        });
      } else {
        if (url.pathname === "/api/message") {
          response = await fetched.json();
          count++;
        }
        await route.fulfill({ response: fetched });
      }
    });
    try {
      await page.goto("http://127.0.0.1:5173");
      await page
        .getByRole("button", { name: "Conversation Demo", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Начать разговор", exact: true })
        .click();
      await page.waitForFunction(
        () => window.__confirmationGate.active > 0,
        null,
        { timeout: 60000 },
      );
      assert.match(
        await page.locator("body").innerText(),
        /Проверьте номер|Нөмірді тексеріңізші/,
      );
      const negative = caseId.endsWith("_no");
      const audio =
        (caseId.includes("kk") ? "kk" : "ru") + (negative ? "_no" : "_yes");
      await page.evaluate(
        (name) => window.__confirmationGate.play(name),
        audio,
      );
      const deadline = Date.now() + 60000;
      while (!count && Date.now() < deadline) await page.waitForTimeout(100);
      assert.equal(count, 1, "exactly one customer/API turn");
      const snapshot = await (
        await context.request.get(
          `http://127.0.0.1:8016/confirmation/check/${sessionId}`,
        )
      ).json();
      result.check = snapshot;
      const finals = await page.evaluate(
        () => window.__confirmationGate.finals,
      );
      assert.equal(finals.length, 1);
      result.visibleTranscript = finals[0].text;
      result.recognition = response.trace.recognition;
      assert.equal(snapshot.iin_fallback, false);
      assert.notEqual(snapshot.status, "handoff");
      if (caseId === "fixture_unresolved") {
        assert.equal(snapshot.phase, "confirmation");
        assert.equal(snapshot.candidate_retained, true);
        assert.equal(snapshot.accepted_expected, false);
        assert.equal(snapshot.lookups, 0);
        assert.deepEqual(response.trace.actions, []);
        assert.match(response.response_text, /Не расслышал/);
        assert.equal(finals[0].text, "No.");
      } else if (negative) {
        assert.equal(snapshot.phase, "segments");
        assert.equal(snapshot.accepted_expected, false);
        assert.equal(response.trace.recognition.confirmation_status, "reject");
      } else {
        assert.equal(snapshot.accepted_expected, true);
        assert.equal(
          response.trace.recognition.verification_method,
          "customer_confirmation",
        );
        assert.equal(snapshot.phase, null);
      }
      if (caseId.startsWith("live_"))
        assert.equal(response.trace.recognition.second_pass_used, false);
      else assert.equal(response.trace.recognition.second_pass_used, true);
      assert.equal(result.errors.length, 0);
      await page.screenshot({
        path: new URL(caseId + ".png", root).pathname.slice(1),
        fullPage: true,
      });
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
      await page
        .getByRole("button", { name: "Завершить", exact: true })
        .click({ timeout: 3000 })
        .catch(() => {});
      result.tracksStopped = await page.evaluate(() =>
        window.__confirmationGate.tracks.every((t) => t.readyState === "ended"),
      );
      if (!result.tracksStopped) result.pass = false;
      results.push(result);
      await writeFile(
        new URL(
          "browser-results-" +
            (process.env.CONFIRMATION_RUN || "main") +
            ".json",
          root,
        ),
        JSON.stringify(results, null, 2),
      );
      console.log(
        JSON.stringify({
          case: caseId,
          pass: result.pass,
          failure: result.failure,
          transcript: result.visibleTranscript,
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
