export interface TtsPlaybackResult {
  firstAudioMs?: number;
  totalMs?: number;
}

export interface TtsService {
  speak(
    text: string,
    language?: string,
    hooks?: TtsPlaybackHooks,
  ): Promise<TtsPlaybackResult>;
  stop(): void;
}

export interface TtsPlaybackHooks {
  onFirstAudio?(): void;
  onAudio?(blob: Blob): void;
  onNearEnd?(playbackSeconds: number): void;
}

/** Development adapter. Resolves immediately and produces no audio. */
export class NoopTtsService implements TtsService {
  async speak(_text: string, _language?: string): Promise<TtsPlaybackResult> {
    return {};
  }

  stop(): void {}
}
