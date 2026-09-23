import type { TtsPlaybackResult, TtsService } from '../tts';

export function localeForLanguage(language?: string): string {
  return language?.toLowerCase().startsWith('kk') ? 'kk-KZ' : 'ru-RU';
}

/** No voice assignment lets the browser use its own default. */
export function selectVoice(
  voices: SpeechSynthesisVoice[],
  language?: string,
): SpeechSynthesisVoice | null {
  const locale = localeForLanguage(language).toLowerCase();
  const prefix = locale.slice(0, 2);
  return voices.find((voice) => voice.lang.toLowerCase() === locale)
    ?? voices.find((voice) => voice.lang.toLowerCase().split('-')[0] === prefix)
    ?? voices.find((voice) => voice.default)
    ?? null;
}

interface Playback {
  cancel(): void;
}

export class BrowserTtsService implements TtsService {
  private active: Playback | null = null;
  private selectedVoice = 'Не выбрано';

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
          synthesis.removeEventListener('voiceschanged', onVoicesChanged);
        } catch {
          // The browser default remains usable if voice-listener cleanup fails.
        }
        resolve(voices);
      };
      try {
        synthesis.addEventListener('voiceschanged', onVoicesChanged);
        timer = setTimeout(() => finish(this.readVoices(synthesis)), 300);
        setCancelWait(() => finish([]));
      } catch {
        finish([]);
      }
    });
  }

  speak(text: string, language?: string): Promise<TtsPlaybackResult> {
    const startedAt = performance.now();
    if (!text.trim()) return Promise.reject(new Error('TTS text is empty.'));
    if (typeof speechSynthesis === 'undefined' || typeof SpeechSynthesisUtterance === 'undefined') {
      return Promise.reject(new Error('Browser speech synthesis is unavailable.'));
    }

    this.stop();
    const synthesis = speechSynthesis;
    return new Promise<TtsPlaybackResult>((resolve, reject) => {
      let utterance: SpeechSynthesisUtterance | null = null;
      let firstAudioMs: number | undefined;
      let cancelWait: (() => void) | null = null;
      let settled = false;

      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        cancelWait?.();
        if (utterance) {
          utterance.onstart = null;
          utterance.onend = null;
          utterance.onerror = null;
        }
        if (this.active === playback) this.active = null;
        if (error) reject(error);
        else resolve({ firstAudioMs, totalMs: Math.max(0, performance.now() - startedAt) });
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
          finish(new DOMException('Speech playback cancelled.', 'AbortError'));
        },
      };
      this.active = playback;

      void this.waitForVoices(synthesis, (cancel) => { cancelWait = cancel; }).then((voices) => {
        if (settled || this.active !== playback) return;
        try {
          const voice = selectVoice(voices, language);
          this.selectedVoice = voice ? `${voice.name} (${voice.lang})` : 'Browser default';
          utterance = new SpeechSynthesisUtterance(text);
          utterance.lang = voice?.lang ?? localeForLanguage(language);
          if (voice) utterance.voice = voice;
          utterance.onstart = () => {
            firstAudioMs = Math.max(0, performance.now() - startedAt);
          };
          utterance.onend = () => {
            if (firstAudioMs === undefined) {
              finish(new Error('Speech synthesis ended without starting playback.'));
            } else {
              finish();
            }
          };
          utterance.onerror = (event) => {
            finish(new Error(`Speech playback failed: ${event.error}.`));
          };
          synthesis.speak(utterance);
        } catch (cause) {
          finish(cause instanceof Error ? cause : new Error(String(cause)));
        }
      }, (cause: unknown) => {
        finish(cause instanceof Error ? cause : new Error(String(cause)));
      });
    });
  }

  stop(): void {
    this.active?.cancel();
  }
}
