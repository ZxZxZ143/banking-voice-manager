import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
} from "react";
import type { VoiceTranscript } from "../../types/agent";
import { redactAuthentication } from "../../runtime/privacy";
import {
  finalVoiceTranscript,
  type VoiceControlsHandle,
} from "./voiceRuntimeBridge";
import { BrowserVoiceInput } from "./BrowserVoiceInput";

type Run = {
  cancelled: boolean;
  sending: boolean;
  completed: boolean;
  ws?: WebSocket;
  context?: AudioContext;
  deadline?: ReturnType<typeof setTimeout>;
};
type Metrics = {
  stt_after_commit_ms: number;
  endpoint_silence_ms: number;
  audio_ms: number;
};

function release(run: Run) {
  run.cancelled = true;
  run.sending = false;
  clearTimeout(run.deadline);
  void run.context?.close().catch(() => {});
  run.ws?.close();
}

export const VoiceControls = forwardRef<
  VoiceControlsHandle,
  {
    sessionId: string;
    enabled: boolean;
    securityQuestion?: unknown;
    onTranscript: (transcript: VoiceTranscript) => void;
  }
>(function VoiceControls(
  { sessionId, enabled, onTranscript, securityQuestion },
  ref,
) {
  const active = useRef<Run | null>(null);
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [pauseMs, setPauseMs] = useState(0);
  const [effectivePause, setEffectivePause] = useState(1600);
  const [silence, setSilence] = useState(0);
  const [status, setStatus] = useState("Готов к проверке");
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [source, setSource] = useState("");
  const transcriptCallback = useRef(onTranscript);
  transcriptCallback.current = onTranscript;
  const microphone = useRef<BrowserVoiceInput | null>(null);
  if (!microphone.current)
    microphone.current = new BrowserVoiceInput((event) => {
      if (event.type === "preparing") {
        setBusy(true);
        setRecording(false);
        setText("");
        setError("");
        setMetrics(null);
        setSource("Микрофон");
        setStatus("Подготавливаем микрофон · речь ещё не передаётся");
      } else if (event.type === "prepared") {
        setStatus("Микрофон подготовлен · речь ещё не передаётся");
        if (typeof event.pause_ms === "number")
          setEffectivePause(event.pause_ms);
      } else if (event.type === "listening") {
        setRecording(true);
        setStatus("Говорите");
      } else if (event.type === "activity") {
        setSilence(event.has_speech ? Number(event.silence_ms) : 0);
        setStatus(
          event.speech
            ? "Слышу речь"
            : event.has_speech
              ? "Пауза — жду продолжения"
              : "Ожидаю речь",
        );
      } else if (event.type === "transcript.partial") {
        setText((previous) => previous + event.delta);
      } else if (event.type === "committed") {
        setRecording(false);
        setStatus("Реплика завершена — получаем итог");
      } else if (event.type === "utterance.final") {
        setBusy(false);
        setRecording(false);
        setText(String(event.text ?? ""));
        setMetrics(event as unknown as Metrics);
        setStatus("Готово");
        const transcript = finalVoiceTranscript(event);
        if (transcript) transcriptCallback.current(transcript);
      } else if (
        event.type === "empty" ||
        event.type === "stopped" ||
        event.type === "error"
      ) {
        setBusy(false);
        setRecording(false);
        setStatus(
          event.type === "empty" ? "Речь не обнаружена" : "Микрофон выключен",
        );
        if (event.type === "error") setError(String(event.message));
      }
    });
  useEffect(
    () => () => {
      if (active.current) release(active.current);
      microphone.current?.stopListening();
    },
    [],
  );

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
    setStatus("Ошибка");
    stop(run);
  }

  async function start(selectedFile?: File, sessionOverride?: string) {
    if (active.current) return;
    const runSessionId = sessionOverride ?? sessionId;
    if (!runSessionId) {
      setError("Сначала начните разговор.");
      return;
    }
    if (!selectedFile) {
      await microphone.current!.startListening(
        runSessionId,
        pauseMs || undefined,
      );
      return;
    }
    microphone.current?.stopListening();
    const run: Run = { cancelled: false, sending: false, completed: false };
    active.current = run;
    setBusy(true);
    setRecording(false);
    setText("");
    setError("");
    setMetrics(null);
    setSilence(0);
    setSource(selectedFile?.name ?? "Микрофон");
    setStatus(
      selectedFile
        ? "Подготавливаем аудиофайл…"
        : "Разрешите доступ к микрофону…",
    );
    run.deadline = setTimeout(
      () => fail(run, "Превышено время сессии. Начните новую запись."),
      150000,
    );
    try {
      const context = new AudioContext({ sampleRate: 24000 });
      run.context = context;
      await context.resume();
      if (run.cancelled) return;
      if (context.sampleRate !== 24000)
        throw new Error("Браузер не поддерживает аудио 24 кГц.");
      let samples: Float32Array | undefined;
      if (selectedFile) {
        if (selectedFile.size > 10_000_000)
          throw new Error("Для стенда выберите файл до 10 МБ.");
        const decoded = await context.decodeAudioData(
          await selectedFile.arrayBuffer(),
        );
        if (decoded.duration > 110)
          throw new Error("Максимальная длительность файла — 110 секунд.");
        samples = decoded.getChannelData(0);
      }
      if (run.cancelled) return;
      setStatus("Подключаем облачное распознавание…");
      const ws = new WebSocket(
        `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/v1/voice`,
      );
      run.ws = ws;
      const send = (buffer: ArrayBuffer) => {
        if (!run.sending || run.cancelled || ws.readyState !== WebSocket.OPEN)
          return;
        if (ws.bufferedAmount > 48000 * 3) {
          fail(run, "Сеть не успевает передавать аудио. Запись остановлена.");
          return;
        }
        ws.send(buffer);
      };
      ws.onopen = () => {
        if (run.cancelled || ws.readyState !== WebSocket.OPEN) return;
        ws.send(
          JSON.stringify({
            type: "start",
            session_id: runSessionId,
            sample_rate: 24000,
            channels: 1,
            ...(pauseMs ? { pause_ms: pauseMs } : {}),
          }),
        );
      };
      ws.onerror = () =>
        fail(
          run,
          "Не удалось подключиться к backend. Проверьте, что он запущен.",
        );
      ws.onclose = () => {
        if (!run.cancelled)
          fail(run, "Соединение закрылось до получения результата.");
      };
      ws.onmessage = ({ data }) => {
        if (run.cancelled) return;
        const event = JSON.parse(data);
        if (event.type === "ready") {
          run.sending = true;
          setRecording(true);
          setStatus(
            selectedFile ? "Передаём файл в реальном времени" : "Говорите",
          );
          if (samples) {
            const audio = samples;
            void (async () => {
              // Append silence to let automatic endpointing finish, without manual commit.
              const total =
                audio.length + 24000 * ((pauseMs || 1600) / 1000 + 1);
              const began = performance.now();
              for (
                let offset = 0;
                offset < total && run.sending && !run.cancelled;
                offset += 2400
              ) {
                const buffer = new ArrayBuffer(4800);
                const view = new DataView(buffer);
                for (let i = 0; i < 2400; i++) {
                  const value = Math.max(
                    -1,
                    Math.min(1, audio[offset + i] ?? 0),
                  );
                  view.setInt16(i * 2, Math.round(value * 32767), true);
                }
                await new Promise((resolve) =>
                  setTimeout(
                    resolve,
                    Math.max(
                      0,
                      began + (offset + 2400) / 24 - performance.now(),
                    ),
                  ),
                );
                send(buffer);
              }
              if (run.sending && !run.cancelled)
                ws.send(JSON.stringify({ type: "finish" }));
            })().catch(() => fail(run, "Не удалось передать аудиофайл."));
          }
        } else if (event.type === "activity") {
          setSilence(event.has_speech ? event.silence_ms : 0);
          setStatus(
            event.speech
              ? "Слышу речь"
              : event.has_speech
                ? "Пауза — жду продолжения"
                : "Ожидаю речь",
          );
        } else if (event.type === "transcript.partial") {
          setText((previous) => previous + event.delta);
        } else if (event.type === "committed") {
          run.sending = false;
          setRecording(false);
          setStatus("Реплика завершена — получаем итог");
        } else if (event.type === "utterance.final") {
          run.completed = true;
          const transcript = finalVoiceTranscript(event);
          setText(typeof event.text === "string" ? event.text : "");
          setMetrics(event);
          setStatus(transcript ? "Готово" : "Пустая транскрипция");
          stop(run);
          if (transcript) onTranscript(transcript);
        } else if (event.type === "empty") {
          setText("");
          setStatus("Речь не обнаружена");
          stop(run);
        } else if (event.type === "error") {
          fail(run, event.message);
        }
      };
    } catch (cause) {
      fail(
        run,
        cause instanceof Error ? cause.message : "Ошибка доступа к аудио.",
      );
    }
  }

  function finish() {
    microphone.current?.finish();
    const run = active.current;
    if (!run?.sending) return;
    setRecording(false);
    setStatus("Завершаем реплику…");
    run.sending = false;
    run.ws?.send(JSON.stringify({ type: "finish" }));
  }

  useImperativeHandle(ref, () => ({
    prepareListening: (activeSessionId) =>
      microphone.current!.prepareListening(
        activeSessionId,
        pauseMs || undefined,
      ),
    playbackReference: (blob) => microphone.current!.playbackReference(blob),
    armNearEnd: (seconds) => microphone.current!.armNearEnd(seconds),
    startListening: (activeSessionId) => start(undefined, activeSessionId),
    pauseListening: () => {
      microphone.current!.pauseListening();
      if (active.current) stop(active.current);
    },
    stopListening: () => {
      microphone.current!.stopListening();
      if (active.current) stop(active.current);
    },
  }));

  function download() {
    const url = URL.createObjectURL(
      new Blob(
        [
          JSON.stringify(
            {
              source,
              text: redactAuthentication(text, securityQuestion),
              pause_ms: pauseMs,
              metrics,
            },
            null,
            2,
          ),
        ],
        { type: "application/json" },
      ),
    );
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "voice-test.json";
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="voice-controls" aria-labelledby="voice-title">
      <h3 id="voice-title">Микрофон</h3>
      <p className="muted">
        После начала разговора микрофон включается автоматически. Финальный
        текст идёт в тот же диалог.
      </p>
      <div className="voice-buttons">
        <button
          type="button"
          disabled={busy || !enabled}
          onClick={() => void start()}
        >
          Начать говорить
        </button>
        <button type="button" disabled={!recording} onClick={finish}>
          Завершить сейчас
        </button>
        <button
          type="button"
          disabled={!busy}
          onClick={() => {
            microphone.current?.stopListening();
            if (active.current) stop(active.current);
            setStatus("Отменено");
          }}
        >
          Отмена
        </button>
      </div>
      <p role="status" className="voice-status">
        {status}
      </p>
      <label htmlFor="voice-transcript">
        Транскрипция {busy ? "· промежуточная" : ""}
      </label>
      <textarea
        id="voice-transcript"
        rows={2}
        readOnly
        value={redactAuthentication(text, securityQuestion)}
        placeholder="Здесь появится распознанная речь…"
      />
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      <details className="developer-tools">
        <summary>Диагностика голоса · пауза, файл, задержки</summary>
        <label>
          <input
            type="checkbox"
            checked={pauseMs === 0}
            disabled={busy}
            onChange={(event) => setPauseMs(event.target.checked ? 0 : 1600)}
          />
          Автоматическая пауза по типу ответа
        </label>
        <label htmlFor="pause">
          Завершать после тишины:{" "}
          {((pauseMs || effectivePause) / 1000).toFixed(2)} с
        </label>
        <input
          id="pause"
          type="range"
          min={500}
          max={5000}
          step={100}
          value={pauseMs || effectivePause}
          disabled={busy}
          onChange={(event) => setPauseMs(Number(event.target.value))}
        />
        <p className="muted">
          Автоматически: короткая пауза для подтверждений, больше времени для
          номера и обычной речи. Ползунок задаёт ручной режим.
        </p>
        <label htmlFor="audio-file">Или проверить запись с телефона</label>
        <input
          id="audio-file"
          type="file"
          accept="audio/*,.m4a"
          disabled={busy}
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <button
          type="button"
          disabled={busy || !file || !enabled}
          onClick={() => file && void start(file)}
        >
          Проверить файл
        </button>
        <progress
          aria-label="Пауза до завершения"
          value={Math.min(silence, pauseMs || effectivePause)}
          max={pauseMs || effectivePause}
        />
        {metrics && (
          <p className="muted">
            Тишина до завершения: {metrics.endpoint_silence_ms} мс · STT после
            завершения: {metrics.stt_after_commit_ms} мс. Это не полная задержка
            ответа агента.
          </p>
        )}
        <button type="button" disabled={!metrics} onClick={download}>
          Скачать результат теста
        </button>
      </details>
    </section>
  );
});
