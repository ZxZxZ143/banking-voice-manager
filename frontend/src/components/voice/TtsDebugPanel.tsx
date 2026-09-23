import { useState } from 'react';
import type { RuntimeStatus } from '../../types/agent';
import type { TtsPlaybackResult } from '../../services/tts';
import type { BrowserTtsService } from '../../services/tts/BrowserTtsService';

const samples = {
  ru: 'Здравствуйте. Чем я могу вам помочь?',
  kk: 'Сәлеметсіз бе. Сізге қалай көмектесе аламын?',
};

export function TtsDebugPanel({ tts, runtimeStatus }: {
  tts: BrowserTtsService;
  runtimeStatus: RuntimeStatus;
}) {
  const [language, setLanguage] = useState<'ru' | 'kk'>('ru');
  const [text, setText] = useState(samples.ru);
  const [playing, setPlaying] = useState(false);
  const [result, setResult] = useState<TtsPlaybackResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function speak() {
    setPlaying(true);
    setResult(null);
    setError(null);
    try {
      setResult(await tts.speak(text, language));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setPlaying(false);
    }
  }

  return (
    <section className="panel" aria-labelledby="tts-debug-title">
      <h2 id="tts-debug-title">Проверка голоса</h2>
      <label htmlFor="tts-language">Язык</label>
      <select id="tts-language" value={language} onChange={(event) => {
        const selected = event.target.value as 'ru' | 'kk';
        setLanguage(selected);
        setText(samples[selected]);
      }}>
        <option value="ru">ru</option>
        <option value="kk">kk</option>
      </select>
      <label htmlFor="tts-text">Текст</label>
      <textarea id="tts-text" rows={2} value={text} onChange={(event) => setText(event.target.value)} />
      <div className="controls">
        <button type="button" onClick={() => { void speak(); }}
          disabled={playing || runtimeStatus === 'speaking' || runtimeStatus === 'processing'}>Speak</button>
        <button type="button" onClick={() => tts.stop()} disabled={!playing}>Stop</button>
      </div>
      <p className="muted">Голос: {tts.lastSelectedVoice}</p>
      {result && <p className="muted">firstAudioMs: {Math.round(result.firstAudioMs ?? 0)} · totalMs: {Math.round(result.totalMs ?? 0)}</p>}
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  );
}
