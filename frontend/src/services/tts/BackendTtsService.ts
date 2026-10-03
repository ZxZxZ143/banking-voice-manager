import type { TtsPlaybackResult, TtsService } from "../tts";
import { BrowserTtsService, localeForLanguage } from "./BrowserTtsService.ts";

/** Backend audio first; explicit browser fallback only before any backend playback. */
export class BackendTtsService implements TtsService {
  private generation = 0;
  private cancelActive: (() => void) | null = null;
  private selectedVoice = "Backend TTS · browser fallback available";

  constructor(
    private readonly fallback: TtsService & {
      readonly lastSelectedVoice?: string;
    } = new BrowserTtsService(),
    private readonly endpoint = "/api/speech/tts",
    private readonly timeoutMs = 35_000,
  ) {}

  get lastSelectedVoice(): string {
    return this.selectedVoice;
  }

  async speak(text: string, language?: string): Promise<TtsPlaybackResult> {
    if (!text.trim() || text.length > 4000)
      throw new Error("Speech text is empty or too long.");
    this.stop();
    const generation = this.generation;
    const started = performance.now();
    const controller = new AbortController();
    const languageCode = localeForLanguage(language).startsWith("kk")
      ? "kk"
      : "ru";
    let timedOut = false;
    let played = false;
    let audio: HTMLAudioElement | null = null;
    let url: string | null = null;
    let rejectPlayback: ((reason: unknown) => void) | null = null;
    this.cancelActive = () => {
      controller.abort();
      audio?.pause();
      rejectPlayback?.(
        new DOMException("Speech playback cancelled.", "AbortError"),
      );
    };
    const timer = setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, this.timeoutMs);
    try {
      const response = await fetch(this.endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, language: languageCode }),
        signal: controller.signal,
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) throw new Error("Backend speech unavailable.");
      const type = response.headers.get("content-type")?.split(";")[0];
      if (type !== "audio/mpeg" && type !== "audio/wav")
        throw new Error("Invalid speech audio type.");
      const blob = await response.blob();
      if (!blob.size || blob.size > 8_000_000)
        throw new Error("Invalid speech audio size.");
      if (generation !== this.generation)
        throw new DOMException("Cancelled", "AbortError");
      clearTimeout(timer);
      url = URL.createObjectURL(blob);
      audio = new Audio(url);
      this.selectedVoice = `Backend TTS (${languageCode})`;
      return await new Promise<TtsPlaybackResult>((resolve, reject) => {
        let firstAudioMs: number | undefined;
        const playbackTimer = setTimeout(() => {
          audio?.pause();
          finish(new Error("Speech playback timed out."));
        }, 180_000);
        const finish = (error?: unknown) => {
          clearTimeout(playbackTimer);
          rejectPlayback = null;
          if (audio) {
            audio.onplaying = null;
            audio.onended = null;
            audio.onerror = null;
          }
          if (error) reject(error);
          else resolve({ firstAudioMs, totalMs: performance.now() - started });
        };
        rejectPlayback = finish;
        audio!.onplaying = () => {
          played = true;
          firstAudioMs ??= performance.now() - started;
        };
        audio!.onended = () =>
          finish(
            played ? undefined : new Error("Audio ended before playback."),
          );
        audio!.onerror = () =>
          finish(new Error("Speech audio playback failed."));
        try {
          void audio!.play().catch(finish);
        } catch (error) {
          finish(error);
        }
      });
    } catch (error) {
      if (generation !== this.generation)
        throw new DOMException("Speech playback cancelled.", "AbortError");
      if (played) throw error; // Never repeat a partly spoken response through fallback.
      audio?.pause();
      this.selectedVoice = timedOut
        ? "Browser fallback · backend timeout"
        : "Browser fallback · backend unavailable";
      const result = await this.fallback.speak(text, languageCode);
      if (generation !== this.generation)
        throw new DOMException("Speech playback cancelled.", "AbortError");
      this.selectedVoice = `Browser fallback: ${this.fallback.lastSelectedVoice ?? languageCode}`;
      return {
        ...result,
        firstAudioMs:
          result.firstAudioMs === undefined
            ? undefined
            : performance.now() -
              started -
              (result.totalMs ?? 0) +
              result.firstAudioMs,
        totalMs: performance.now() - started,
      };
    } finally {
      controller.abort();
      clearTimeout(timer);
      if (audio) {
        audio.onplaying = null;
        audio.onended = null;
        audio.onerror = null;
        audio.pause();
        audio.removeAttribute("src");
        audio.load();
      }
      if (url) URL.revokeObjectURL(url);
      if (generation === this.generation) this.cancelActive = null;
    }
  }

  stop(): void {
    this.generation += 1;
    this.cancelActive?.();
    this.cancelActive = null;
    this.fallback.stop();
  }
}
