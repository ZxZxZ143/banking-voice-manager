import { useEffect, useRef, useState } from 'react';

type Run = {
  cancelled: boolean;
  sending: boolean;
  completed: boolean;
  ws?: WebSocket;
  stream?: MediaStream;
  context?: AudioContext;
  node?: AudioWorkletNode;
  deadline?: ReturnType<typeof setTimeout>;
};
type Metrics = { stt_after_commit_ms: number; endpoint_silence_ms: number; audio_ms: number };

function release(run: Run) {
  run.cancelled = true;
  run.sending = false;
  clearTimeout(run.deadline);
  run.stream?.getTracks().forEach(track => track.stop());
  run.node?.disconnect();
  void run.context?.close().catch(() => {});
  run.ws?.close();
}

export function VoiceControls({ sessionId, onTranscript }: {
  sessionId: string; onTranscript: (text: string) => void;
}) {
  const active = useRef<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [pauseMs, setPauseMs] = useState(2500);
  const [silence, setSilence] = useState(0);
  const [status, setStatus] = useState('Готов к проверке');
  const [text, setText] = useState('');
  const [error, setError] = useState('');
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState('');
  useEffect(() => () => { if (active.current) release(active.current); }, []);

  function stop(run: Run) {
    release(run);
    if (active.current === run) {
      active.current = null;
      setBusy(false);
      setRecording(false);
    }
  }

  function fail(run: Run, message: string) {
    if (run.cancelled) return;
    setError(message);
    setStatus('Ошибка');
    stop(run);
  }

  async function start(selectedFile?: File) {
    if (active.current) return;
    const run: Run = { cancelled: false, sending: false, completed: false };
    active.current = run;
    setBusy(true); setRecording(false); setText(''); setError(''); setMetrics(null); setSilence(0);
    setSource(selectedFile?.name ?? 'Микрофон');
    setStatus(selectedFile ? 'Подготавливаем аудиофайл…' : 'Разрешите доступ к микрофону…');
    run.deadline = setTimeout(() => fail(run, 'Превышено время сессии. Начните новую запись.'), 150000);
    try {
      const context = new AudioContext({ sampleRate: 24000 });
      run.context = context;
      await context.resume();
      if (run.cancelled) return;
      if (context.sampleRate !== 24000) throw new Error('Браузер не поддерживает аудио 24 кГц.');
      let samples: Float32Array | undefined;
      if (selectedFile) {
        if (selectedFile.size > 10_000_000) throw new Error('Для стенда выберите файл до 10 МБ.');
        const decoded = await context.decodeAudioData(await selectedFile.arrayBuffer());
        if (decoded.duration > 110) throw new Error('Максимальная длительность файла — 110 секунд.');
        samples = decoded.getChannelData(0);
      } else {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        });
        if (run.cancelled) { stream.getTracks().forEach(track => track.stop()); return; }
        run.stream = stream;
        await context.audioWorklet.addModule('/pcm-worklet.js');
      }
      if (run.cancelled) return;
      setStatus('Подключаем облачное распознавание…');
      const ws = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/api/v1/voice`);
      run.ws = ws;
      const send = (buffer: ArrayBuffer) => {
        if (!run.sending || run.cancelled || ws.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > 48000 * 3) {
          fail(run, 'Сеть не успевает передавать аудио. Запись остановлена.');
          return;
        }
        ws.send(buffer);
      };
      ws.onopen = () => ws.send(JSON.stringify({
        type: 'start', session_id: sessionId, sample_rate: 24000, channels: 1, pause_ms: pauseMs,
      }));
      ws.onerror = () => fail(run, 'Не удалось подключиться к backend. Проверьте, что он запущен.');
      ws.onclose = () => {
        if (!run.cancelled) fail(run, 'Соединение закрылось до получения результата.');
      };
      ws.onmessage = ({ data }) => {
        if (run.cancelled) return;
        const event = JSON.parse(data);
        if (event.type === 'ready') {
          run.sending = true;
          setRecording(true); setStatus(selectedFile ? 'Передаём файл в реальном времени' : 'Говорите');
          if (samples) {
            const audio = samples;
            void (async () => {
              // Append silence to let automatic endpointing finish, without manual commit.
              const total = audio.length + 24000 * (pauseMs / 1000 + 1);
              const began = performance.now();
              for (let offset = 0; offset < total && run.sending && !run.cancelled; offset += 2400) {
                const buffer = new ArrayBuffer(4800);
                const view = new DataView(buffer);
                for (let i = 0; i < 2400; i++) {
                  const value = Math.max(-1, Math.min(1, audio[offset + i] ?? 0));
                  view.setInt16(i * 2, Math.round(value * 32767), true);
                }
                await new Promise(resolve => setTimeout(resolve,
                  Math.max(0, began + (offset + 2400) / 24 - performance.now())));
                send(buffer);
              }
              if (run.sending && !run.cancelled) ws.send(JSON.stringify({ type: 'finish' }));
            })().catch(() => fail(run, 'Не удалось передать аудиофайл.'));
          } else if (run.stream) {
            try {
              const node = new AudioWorkletNode(context, 'pcm-capture');
              run.node = node;
              node.port.onmessage = ({ data: chunk }) => {
                if (chunk === 'flushed') {
                  run.sending = false;
                  run.stream?.getTracks().forEach(track => track.stop());
                  if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'finish' }));
                } else send(chunk);
              };
              context.createMediaStreamSource(run.stream).connect(node);
              const mute = context.createGain(); mute.gain.value = 0;
              node.connect(mute).connect(context.destination);
            } catch { fail(run, 'Не удалось запустить захват микрофона.'); }
          }
        } else if (event.type === 'activity') {
          setSilence(event.has_speech ? event.silence_ms : 0);
          setStatus(event.speech ? 'Слышу речь' : event.has_speech ? 'Пауза — жду продолжения' : 'Ожидаю речь');
        } else if (event.type === 'transcript.partial') {
          setText(previous => previous + event.delta);
        } else if (event.type === 'committed') {
          run.sending = false; setRecording(false); setStatus('Реплика завершена — получаем итог');
          run.stream?.getTracks().forEach(track => track.stop());
          run.node?.disconnect();
        } else if (event.type === 'utterance.final') {
          run.completed = true;
          setText(event.text); setMetrics(event); setStatus('Готово');
          onTranscript(event.text); stop(run);
        } else if (event.type === 'empty') {
          setText(''); setStatus('Речь не обнаружена'); stop(run);
        } else if (event.type === 'error') {
          fail(run, event.message);
        }
      };
    } catch (cause) {
      fail(run, cause instanceof Error ? cause.message : 'Ошибка доступа к аудио.');
    }
  }

  function finish() {
    const run = active.current;
    if (!run?.sending) return;
    setRecording(false); setStatus('Завершаем реплику…');
    if (run.node) run.node.port.postMessage('finish');
    else { run.sending = false; run.ws?.send(JSON.stringify({ type: 'finish' })); }
  }

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify({ source, text, pause_ms: pauseMs, metrics }, null, 2)],
      { type: 'application/json' }));
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'voice-test.json'; anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="voice-controls" aria-labelledby="voice-title">
    <h3 id="voice-title">Тестовый стенд · русский и казахский</h3>
    <p className="muted">Аудио передаётся в OpenAI. Ответы бота и TTS пока не подключены.</p>
    <label htmlFor="pause">Завершать после тишины: {(pauseMs / 1000).toFixed(1)} с</label>
    <input id="pause" type="range" min={500} max={5000} step={100} value={pauseMs}
      disabled={busy} onChange={event => setPauseMs(Number(event.target.value))} />
    <p className="muted">2,5 с — запас для запинок. Более короткая пауза ускоряет результат, но может обрезать мысль.</p>
    <div className="voice-buttons">
      <button disabled={busy} onClick={() => void start()}>Начать говорить</button>
      <button disabled={!recording} onClick={finish}>Завершить сейчас</button>
      <button disabled={!busy} onClick={() => { if (active.current) stop(active.current); setStatus('Отменено'); }}>Отмена</button>
    </div>
    <label htmlFor="audio-file">Или проверить запись с телефона</label>
    <input id="audio-file" type="file" accept="audio/*,.m4a" disabled={busy}
      onChange={event => setFile(event.target.files?.[0] ?? null)} />
    <button disabled={busy || !file} onClick={() => file && void start(file)}>Проверить файл</button>
    <p role="status" className="voice-status">{status}</p>
    <progress aria-label="Пауза до завершения" value={Math.min(silence, pauseMs)} max={pauseMs} />
    <label htmlFor="voice-transcript">Транскрипция {busy ? '· промежуточная' : ''}</label>
    <textarea id="voice-transcript" rows={5} readOnly value={text} placeholder="Здесь появится распознанная речь…" />
    {metrics && <p className="muted">Тишина до завершения: {metrics.endpoint_silence_ms} мс ·
      STT после завершения: {metrics.stt_after_commit_ms} мс. Это не полная задержка ответа агента.</p>}
    {error && <p className="error" role="alert">{error}</p>}
    <button disabled={!metrics} onClick={download}>Скачать результат теста</button>
  </section>;
}
