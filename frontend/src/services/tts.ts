export interface TtsPlaybackResult {
  firstAudioMs?: number;
  totalMs?: number;
}

export interface TtsService {
  speak(text: string, language?: string): Promise<TtsPlaybackResult>;
  stop(): void;
}

/** Development adapter. Resolves immediately and produces no audio. */
export class NoopTtsService implements TtsService {
  async speak(_text: string, _language?: string): Promise<TtsPlaybackResult> {
    return {};
  }

  stop(): void {}
}
