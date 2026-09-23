export function TracePanel({ trace }: { trace: unknown }) {
  return (
    <aside className="panel" aria-labelledby="trace-title">
      <h2 id="trace-title">Последняя трассировка</h2>
      <details>
        <summary>Сырые данные API</summary>
        <pre>{trace == null ? 'Трассировки пока нет.' : JSON.stringify(trace, null, 2)}</pre>
      </details>
    </aside>
  );
}
