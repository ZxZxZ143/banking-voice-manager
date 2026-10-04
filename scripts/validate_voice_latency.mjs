/** Actual Conversation Demo + AudioWorklet + WebSocket, with timed synthetic mic.
 * Live STT/TTS/Router; isolated synthetic server state. No physical acoustic claim.
 * Set PLAYWRIGHT_MODULE to an installed playwright module if outside node_modules.
 */
import { createRequire } from "node:module";
import { writeFile, mkdir } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const root = new URL("../work/voice-latency/", import.meta.url);
await mkdir(root, { recursive: true });
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1100 },
});
const cases = (
  process.env.VOICE_CASES ||
  "short_reply,yes,digit_correction,letter_correction,phone,iin,region,insurance,risk"
).split(",");
const repetitions = Number(process.env.VOICE_REPETITIONS || 1);
const results = [];
try {
  for (let repetition = 0; repetition < repetitions; repetition++)
    for (const caseId of cases) {
      const page = await context.newPage();
      let sessionId,
        lastResponse,
        messageCount = 0;
      const failures = [];
      page.on("pageerror", (error) => failures.push(error.name));
      await page.addInitScript(() => {
        const fixture = {
          timings: [],
          audios: [],
          sentAt: null,
          overlapMs: null,
          permissions: 0,
          tracks: [],
          armed: true,
          userAudio: null,
          sources: [],
          context: null,
          echo: false,
          echoAudio: null,
        };
        window.__voiceGate = fixture;
        const NativeWebSocket = window.WebSocket;
        window.WebSocket = new Proxy(NativeWebSocket, {
          construct(Target, args) {
            const url = new URL(String(args[0]));
            if (url.pathname === "/api/v1/voice")
              args[0] = "ws://127.0.0.1:8013/api/v1/voice";
            return Reflect.construct(Target, args);
          },
        });
        window.addEventListener("voice-timing", (event) =>
          fixture.timings.push(event.detail),
        );
        navigator.mediaDevices.getUserMedia = async () => {
          fixture.permissions++;
          fixture.context ??= new AudioContext({ sampleRate: 24000 });
          await fixture.context.resume();
          const destination = fixture.context.createMediaStreamDestination();
          fixture.sources.push(destination);
          fixture.tracks.push(...destination.stream.getTracks());
          return destination.stream;
        };
        fixture.load = async (url) => {
          fixture.context ??= new AudioContext({ sampleRate: 24000 });
          const response = await fetch(url);
          fixture.userAudio = await fixture.context.decodeAudioData(
            await response.arrayBuffer(),
          );
        };
        fixture.play = (audio) => {
          const source = fixture.context.createBufferSource();
          source.buffer = fixture.echo ? fixture.echoAudio : fixture.userAudio;
          for (const destination of fixture.sources) {
            if (
              destination.stream
                .getTracks()
                .some((track) => track.readyState === "live")
            )
              source.connect(destination);
          }
          source.start(0, fixture.echo ? audio.currentTime : 0);
          fixture.sentAt = performance.now();
        };
        const NativeAudio = window.Audio;
        window.Audio = new Proxy(NativeAudio, {
          construct(Target, args) {
            const audio = new Target(...args);
            fixture.audios.push(audio);
            if (fixture.echo)
              void fetch(args[0])
                .then((response) => response.arrayBuffer())
                .then((bytes) => fixture.context.decodeAudioData(bytes))
                .then((buffer) => {
                  fixture.echoAudio = buffer;
                });
            const timer = setInterval(() => {
              if (
                fixture.armed &&
                fixture.userAudio &&
                !audio.paused &&
                Number.isFinite(audio.duration) &&
                audio.duration - audio.currentTime <= 0.35 &&
                audio.duration - audio.currentTime > 0.1
              ) {
                fixture.armed = false;
                fixture.overlapMs = (audio.duration - audio.currentTime) * 1000;
                fixture.play(audio);
              }
            }, 5);
            audio.addEventListener("ended", () => clearInterval(timer), {
              once: true,
            });
            audio.addEventListener("emptied", () => clearInterval(timer), {
              once: true,
            });
            return audio;
          },
        });
      });
      await page.route(/\/(api|validation)\//, async (route) => {
        const request = route.request();
        const url = new URL(request.url());
        const response = await route.fetch({
          url: "http://127.0.0.1:8013" + url.pathname + url.search,
          timeout: 90000,
        });
        if (url.pathname === "/api/conversation/start") {
          const value = await response.json();
          sessionId = value.session_id;
          const seeded = await context.request.post(
            `http://127.0.0.1:8013/validation/seed/${caseId === "echo" ? "yes" : caseId}/${sessionId}`,
          );
          const seed = await seeded.json();
          await route.fulfill({
            response,
            json: { ...value, response_text: seed.response_text },
          });
        } else {
          if (url.pathname === "/api/message") {
            lastResponse = await response.json();
            messageCount++;
          }
          if (response.status() >= 400)
            failures.push(
              `HTTP_${response.status()}_${url.pathname.split("/").at(-1)}`,
            );
          await route.fulfill({ response });
        }
      });
      const result = {
        case: caseId,
        repetition,
        provider: "live",
        microphone: "timed synthetic MediaStream",
        failures,
      };
      try {
        await page.goto("http://127.0.0.1:5173");
        await page
          .getByRole("button", { name: "Conversation Demo", exact: true })
          .click();
        await page.evaluate(async (id) => {
          window.__voiceGate.echo = id === "echo";
          await window.__voiceGate.load(
            "/validation/audio/" + (id === "echo" ? "yes" : id),
          );
        }, caseId);
        await page
          .getByRole("button", { name: "Начать разговор", exact: true })
          .click();
        if (caseId === "echo") {
          await page.waitForFunction(
            () =>
              window.__voiceGate.timings.some(
                (item) => item.event === "input.active",
              ),
            null,
            { timeout: 60000 },
          );
          await page.waitForTimeout(5000);
          result.messageCount = messageCount;
          result.pass = messageCount === 0 && failures.length === 0;
          if (!result.pass)
            throw new Error("Assistant echo created a user turn");
          continue;
        }
        const deadline = Date.now() + 120000;
        while (!messageCount && Date.now() < deadline)
          await page.waitForTimeout(200);
        if (!messageCount) throw new Error("No voice turn within deadline");
        await page.waitForFunction(
          () =>
            window.__voiceGate.timings.filter((item) =>
              ["agent.first_audio", "readback.first_audio"].includes(
                item.event,
              ),
            ).length >= 2,
          null,
          { timeout: 60000 },
        );
        const observation = await page.evaluate(() => ({
          timings: window.__voiceGate.timings,
          overlapMs: window.__voiceGate.overlapMs,
          permissions: window.__voiceGate.permissions,
          sentAt: window.__voiceGate.sentAt,
        }));
        const check = await (
          await context.request.get(
            `http://127.0.0.1:8013/validation/check/${sessionId}`,
          )
        ).json();
        Object.assign(result, observation, {
          check,
          messageCount,
          phase: lastResponse?.trace?.conversation_phase,
          recognition: lastResponse?.trace?.recognition?.outcome,
          language: lastResponse?.state?.response_language,
        });
        if (
          ["digit_correction", "letter_correction"].includes(caseId) &&
          !check.pending_matches
        )
          throw new Error("Pending candidate mismatch");
        if (["digit_correction", "letter_correction"].includes(caseId)) {
          const transcript = await page
            .locator(".message-user p")
            .first()
            .textContent();
          // JavaScript's word boundary is ASCII-only, so check Cyrillic words explicitly.
          result.firstWordPreserved = (
            caseId === "letter_correction"
              ? /^нет(?:\s|[.,!?:;]|$)/iu
              : /^последняя(?:\s|[.,!?:;]|$)/iu
          ).test(transcript?.trim() ?? "");
          if (!result.firstWordPreserved)
            throw new Error("Leading correction word missing");
        }
        if (["phone", "iin"].includes(caseId)) {
          result.canonicalMatch = check.pending_matches;
          result.safeRecognitionRepair =
            !check.pending_matches &&
            !check.provided &&
            check.lookups === 0 &&
            ["repair_required", "confirmation_required"].includes(
              result.recognition,
            );
          if (!result.canonicalMatch && !result.safeRecognitionRepair)
            throw new Error("Unsafe identifier outcome");
        }
        if (caseId === "yes" && !lastResponse?.trace?.recognition?.accepted)
          throw new Error("Confirmation not accepted");
        if (caseId === "region" && !check.region_matches)
          throw new Error("Region mismatch");
        if (
          ["short_reply", "insurance", "risk"].includes(caseId) &&
          check.phase !== "wrap_up"
        )
          throw new Error("Wrap-up missing");
        if (caseId === "letter_correction")
          await page.screenshot({
            path: new URL("conversation-correction.png", root).pathname.slice(
              1,
            ),
            fullPage: true,
          });
        result.pass =
          failures.length === 0 &&
          observation.overlapMs >= 100 &&
          observation.overlapMs <= 400;
        if (
          [
            "letter_correction",
            "digit_correction",
            "insurance",
            "risk",
          ].includes(caseId)
        ) {
          const confirmation = [
            "letter_correction",
            "digit_correction",
          ].includes(caseId);
          await page.evaluate(
            async (id) => {
              await window.__voiceGate.load("/validation/audio/" + id);
              window.__voiceGate.armed = true;
            },
            confirmation ? "yes" : "no_more",
          );
          const followupDeadline = Date.now() + 90000;
          while (messageCount < 2 && Date.now() < followupDeadline)
            await page.waitForTimeout(200);
          if (messageCount !== 2)
            throw new Error("Follow-up voice turn missing or recognition loop");
          result.finalConfirmation = confirmation
            ? lastResponse?.trace?.recognition?.accepted === true
            : undefined;
          result.ended = !confirmation
            ? lastResponse?.conversation_status === "ended"
            : undefined;
          if (confirmation && !result.finalConfirmation)
            throw new Error(
              "Corrected full read-back was not finally confirmed",
            );
          if (!confirmation && !result.ended)
            throw new Error("No-more-questions did not end the conversation");
        }
      } catch (error) {
        result.pass = false;
        failures.push(error.message);
        result.alerts = await page
          .getByRole("alert")
          .allTextContents()
          .catch(() => []);
        await writeFile(
          new URL("failed-synthetic-fixture.json", root),
          JSON.stringify(
            {
              case: caseId,
              user: await page.locator(".message-user").allTextContents(),
              response: lastResponse?.response_text,
            },
            null,
            2,
          ),
        );
        await page.screenshot({
          path: new URL("failed-browser.png", root).pathname.slice(1),
          fullPage: true,
        });
      } finally {
        await page
          .getByRole("button", { name: "Завершить", exact: true })
          .click({ timeout: 2000 })
          .catch(() => {});
        result.tracksStopped = await page
          .evaluate(() =>
            window.__voiceGate.tracks.every(
              (track) => track.readyState === "ended",
            ),
          )
          .catch(() => false);
        if (!result.tracksStopped) {
          result.pass = false;
          failures.push("Microphone track remained live after stop");
        }
        results.push(result);
        await writeFile(
          new URL("browser-results.json", root),
          JSON.stringify(results, null, 2),
        );
        console.log(
          JSON.stringify({
            case: caseId,
            repetition,
            pass: result.pass,
            failures,
          }),
        );
        await page.unrouteAll({ behavior: "ignoreErrors" });
        await page.close();
      }
    }
} finally {
  await browser.close();
}
if (results.some((result) => !result.pass)) process.exitCode = 1;
