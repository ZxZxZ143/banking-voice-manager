/** Readiness at immutable 5e850d3 frontend; current prototype playback, live providers. */
import { createRequire } from "node:module";
import { writeFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const browser = await chromium.launch({
  channel: "chrome",
  headless: true,
  args: ["--autoplay-policy=no-user-gesture-required"],
});
const results = { baseline: [], tts: [] };
try {
  const context = await browser.newContext({
    extraHTTPHeaders: { Origin: "http://127.0.0.1:5173" },
  });
  for (let repetition = 0; repetition < 3; repetition++) {
    const page = await context.newPage();
    await page.route(/\/api\//, async (route) => {
      const url = new URL(route.request().url());
      const response = await route.fetch({
        url: "http://127.0.0.1:8013" + url.pathname + url.search,
        timeout: 60000,
      });
      await route.fulfill({ response });
    });
    await page.addInitScript(() => {
      window.__baseline = {};
      navigator.mediaDevices.getUserMedia = async () => {
        const context = new AudioContext({ sampleRate: 24000 });
        await context.resume();
        return context.createMediaStreamDestination().stream;
      };
      const NativeAudio = window.Audio,
        NativeWebSocket = window.WebSocket;
      window.Audio = new Proxy(NativeAudio, {
        construct(Target, args) {
          const audio = new Target(...args);
          audio.addEventListener("ended", () => {
            window.__baseline.ttsEnd = performance.now();
          });
          return audio;
        },
      });
      window.WebSocket = new Proxy(NativeWebSocket, {
        construct(Target, args) {
          args[0] = "ws://127.0.0.1:8013/api/v1/voice";
          const socket = new Target(...args);
          socket.addEventListener("message", (event) => {
            if (JSON.parse(event.data).type === "ready")
              window.__baseline.ready = performance.now();
          });
          return socket;
        },
      });
    });
    try {
      await page.goto("http://127.0.0.1:5174");
      await page
        .getByRole("button", { name: "Conversation Demo", exact: true })
        .click();
      await page
        .getByRole("button", { name: "Начать разговор", exact: true })
        .click();
      await page.waitForFunction(
        () => window.__baseline.ready && window.__baseline.ttsEnd,
        null,
        { timeout: 60000 },
      );
      results.baseline.push(
        await page.evaluate(() => ({
          tts_end_to_ready_ms:
            window.__baseline.ready - window.__baseline.ttsEnd,
        })),
      );
    } catch (error) {
      results.baseline.push({
        failure: error.name,
        observed: await page.evaluate(() => window.__baseline),
        alerts: await page.getByRole("alert").allTextContents(),
      });
    }
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await page.close();
  }
  if (!process.env.BASELINE_ONLY) {
    const page = await context.newPage();
    await page.goto("http://127.0.0.1:8011");
    for (const [mode, sample] of [
      ["buffered", "ru_greeting"],
      ["streaming", "ru_greeting"],
      ["buffered", "ru_greeting"],
      ["streaming", "ru_greeting"],
      ["buffered", "ru_greeting"],
      ["streaming", "ru_greeting"],
      ["streaming", "kk_greeting"],
    ]) {
      try {
        await page.evaluate(
          ([mode, sample]) => {
            document.querySelector("#results").textContent = "";
            run(mode, sample);
          },
          [mode, sample],
        );
        await page.waitForFunction(
          () =>
            document
              .querySelector("#results")
              .textContent.includes("total_playback_ms"),
          null,
          { timeout: 60000 },
        );
        results.tts.push({
          mode,
          sample,
          events: await page.locator("#results").textContent(),
        });
      } catch (error) {
        results.tts.push({ mode, sample, failure: error.name });
      }
    }
    await page.evaluate(() => run("streaming", "ru_greeting"));
    await page.waitForTimeout(2500);
    await page.evaluate(() => stop());
    results.cancelStopped = await page
      .locator("#audio")
      .evaluate((audio) => audio.paused && !audio.getAttribute("src"));
  }
} finally {
  await writeFile(
    new URL("../work/voice-latency/startup-results.json", import.meta.url),
    JSON.stringify(results, null, 2),
  );
  console.log(
    JSON.stringify({
      baseline: results.baseline,
      ttsSamples: results.tts.length,
      cancelStopped: results.cancelStopped,
    }),
  );
  await browser.close();
}
