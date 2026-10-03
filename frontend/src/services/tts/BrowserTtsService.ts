import type { TtsPlaybackResult, TtsService } from "../tts";

export function localeForLanguage(language?: string): string {
  return language?.toLowerCase().startsWith("kk") ? "kk-KZ" : "ru-RU";
}

/** No voice assignment lets the browser use its own default. */
export function selectVoice(
  voices: SpeechSynthesisVoice[],
  language?: string,
): SpeechSynthesisVoice | null {
  const locale = localeForLanguage(language).toLowerCase();
  const prefix = locale.slice(0, 2);
  const matching = voices.filter(
    (voice) => voice.lang.toLowerCase().split(/[-_]/)[0] === prefix,
  );
  const score = (voice: SpeechSynthesisVoice) =>
    (/natural|neural|online/i.test(voice.name) ? 10 : 0) +
    (voice.lang.toLowerCase() === locale ? 2 : 0) +
    (voice.default ? 1 : 0);
  return (
    matching.sort(
      (a, b) => score(b) - score(a) || a.name.localeCompare(b.name),
    )[0] ??
    voices.find((voice) => voice.default) ??
    null
  );
}

interface Playback {
  cancel(): void;
}

export class BrowserTtsService implements TtsService {
  private active: Playback | null = null;
  private selectedVoice = "Не выбрано";
  private readonly voicesByLocale = new Map<string, string>();

  get lastSelectedVoice(): string {
    return this.selectedVoice;
  }

  private readVoices(synthesis: SpeechSynthesis): SpeechSynthesisVoice[] {
    try {
      return synthesis.getVoices();
    } catch {
      return [];
    }
  }

  private waitForVoices(
    synthesis: SpeechSynthesis,
    setCancelWait: (cancel: () => void) => void,
  ): Promise<SpeechSynthesisVoice[]> {
    const available = this.readVoices(synthesis);
    if (available.length > 0) return Promise.resolve(available);

    return new Promise((resolve) => {
      let timer: ReturnType<typeof setTimeout> | undefined;
      let settled = false;
      const onVoicesChanged = () => {
        const voices = this.readVoices(synthesis);
        if (voices.length > 0) finish(voices);
      };
      const finish = (voices: SpeechSynthesisVoice[]) => {
        if (settled) return;
        settled = true;
        if (timer !== undefined) clearTimeout(timer);
        try {
          synthesis.removeEventListener("voiceschanged", onVoicesChanged);
        } catch {
          // The browser default remains usable if voice-listener cleanup fails.
        }
        resolve(voices);
      };
      try {
        synthesis.addEventListener("voiceschanged", onVoicesChanged);
        timer = setTimeout(() => finish(this.readVoices(synthesis)), 300);
        setCancelWait(() => finish([]));
      } catch {
        finish([]);
      }
    });
  }

  speak(text: string, language?: string): Promise<TtsPlaybackResult> {
    const startedAt = performance.now();
    if (!text.trim()) return Promise.reject(new Error("TTS text is empty."));
    if (
      typeof speechSynthesis === "undefined" ||
      typeof SpeechSynthesisUtterance === "undefined"
    ) {
      return Promise.reject(
        new Error("Browser speech synthesis is unavailable."),
      );
    }

    this.stop();
    const synthesis = speechSynthesis;
    return new Promise<TtsPlaybackResult>((resolve, reject) => {
      let utterance: SpeechSynthesisUtterance | null = null;
      let firstAudioMs: number | undefined;
      let cancelWait: (() => void) | null = null;
      let playbackTimer: ReturnType<typeof setTimeout> | undefined;
      let settled = false;

      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        if (playbackTimer !== undefined) clearTimeout(playbackTimer);
        cancelWait?.();
        if (utterance) {
          utterance.onstart = null;
          utterance.onend = null;
          utterance.onerror = null;
        }
        if (this.active === playback) this.active = null;
        if (error) reject(error);
        else
          resolve({
            firstAudioMs,
            totalMs: Math.max(0, performance.now() - startedAt),
          });
      };

      const playback: Playback = {
        cancel: () => {
          if (settled) return;
          cancelWait?.();
          if (utterance) {
            utterance.onstart = null;
            utterance.onend = null;
            utterance.onerror = null;
          }
          try {
            synthesis.cancel();
          } catch {
            // Settle the pending call even if the browser rejects cancellation.
          }
          finish(new DOMException("Speech playback cancelled.", "AbortError"));
        },
      };
      this.active = playback;

      void this.waitForVoices(synthesis, (cancel) => {
        cancelWait = cancel;
      }).then(
        (voices) => {
          if (settled || this.active !== playback) return;
          try {
            const locale = localeForLanguage(language);
            const previous = this.voicesByLocale.get(locale);
            const voice =
              voices.find(
                (candidate) =>
                  `${candidate.name}|${candidate.lang}` === previous,
              ) ?? selectVoice(voices, language);
            const matchesLocale =
              voice?.lang.toLowerCase().split(/[-_]/)[0] === locale.slice(0, 2);
            if (voice && matchesLocale)
              this.voicesByLocale.set(locale, `${voice.name}|${voice.lang}`);
            this.selectedVoice =
              voice && matchesLocale
                ? `${voice.name} (${voice.lang})`
                : `Browser default (${locale}; matching voice unavailable)`;
            utterance = new SpeechSynthesisUtterance(text);
            utterance.lang = locale;
            if (voice && matchesLocale) utterance.voice = voice;
            utterance.rate = 0.97;
            utterance.pitch = 1;
            utterance.volume = 1;
            utterance.onstart = () => {
              firstAudioMs = Math.max(0, performance.now() - startedAt);
            };
            utterance.onend = () => {
              if (firstAudioMs === undefined) {
                finish(
                  new Error(
                    "Speech synthesis ended without starting playback.",
                  ),
                );
              } else {
                finish();
              }
            };
            utterance.onerror = (event) => {
              finish(new Error(`Speech playback failed: ${event.error}.`));
            };
            // Some browser engines never emit onend/onerror. Bound that wait so
            // a successful terminal response cannot leave the UI in speaking.
            playbackTimer = setTimeout(
              () => {
                finish(new Error("Speech playback timed out."));
                try {
                  synthesis.cancel();
                } catch {
                  /* Playback has already settled. */
                }
              },
              Math.min(180_000, Math.max(15_000, text.length * 120 + 5_000)),
            );
            synthesis.speak(utterance);
          } catch (cause) {
            finish(cause instanceof Error ? cause : new Error(String(cause)));
          }
        },
        (cause: unknown) => {
          finish(cause instanceof Error ? cause : new Error(String(cause)));
        },
      );
    });
  }

  stop(): void {
    this.active?.cancel();
  }
}
