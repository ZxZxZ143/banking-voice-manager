import type { TraceRecord } from '../../types/contracts';

export function TracePanel({ trace }: { trace: TraceRecord | null }) {
  return (
    <aside className="panel" aria-labelledby="trace-title">
      <h2 id="trace-title">Трассировка для супервизора</h2>
      {trace ? <pre>{JSON.stringify(trace, null, 2)}</pre> : (
        <div className="empty-state">
          <p>Трассировок пока нет.</p>
          <p>Здесь появятся распознанный текст, сценарии, краткое объяснение,
            извлечённые параметры, действия и измеренные задержки.</p>
        </div>
      )}
    </aside>
  );
}
