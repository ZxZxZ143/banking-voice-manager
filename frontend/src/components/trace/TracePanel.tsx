import type { ScenarioView, TraceViewModel } from './traceViewModel';

function ScenarioList({ items, primary = false }: { items: ScenarioView[]; primary?: boolean }) {
  return (
    <ol className={primary ? 'scenario-list primary-scenarios' : 'scenario-list'}>
      {items.map((item, index) => (
        <li key={`${item.id}-${index}`}>
          <span className="scenario-id">{item.id}</span>
          {item.name && <span>{item.name}</span>}
          {item.confidence && <strong className="confidence">{item.confidence}</strong>}
        </li>
      ))}
    </ol>
  );
}

export function TracePanel({ view }: { view: TraceViewModel }) {
  return (
    <aside className="panel trace-panel" aria-labelledby="trace-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">Для супервизора</p>
          <h2 id="trace-title">Маршрутизация и контекст</h2>
        </div>
        {view.mock && <span className="badge mock-badge">MOCK</span>}
      </div>
      {!view.hasData && <p className="empty-state">Данных трассировки пока нет.</p>}
      {view.hasData && (
        <>
          {view.turn !== null && <p className="trace-turn">Ход {view.turn}</p>}
          <div className="trace-summary">
            {view.language && <p><span className="field-label">Язык</span><strong>{view.language}</strong></p>}
            {view.conversationStatus && <p><span className="field-label">Диалог</span><strong>{view.conversationStatus}</strong></p>}
          </div>
          {view.transcript && <section className="trace-section"><h3>Транскрипт</h3><p>{view.transcript}</p></section>}
          {view.scenarios.length > 0 && (
            <section className="trace-section">
              <h3>Выбранные сценарии</h3>
              <ScenarioList items={view.scenarios} primary />
            </section>
          )}
          {view.alternatives.length > 0 && (
            <section className="trace-section">
              <h3>Альтернативы</h3>
              <ScenarioList items={view.alternatives} />
            </section>
          )}
          {view.reason && <section className="trace-section"><h3>Краткое объяснение</h3><p>{view.reason}</p></section>}
          {(view.activeScenario || view.scenarioStack.length > 0 || view.pendingScenarios.length > 0) && (
            <section className="trace-section">
              <h3>Состояние сценариев</h3>
              {view.activeScenario && <><p className="field-label">Активный</p><ScenarioList items={[view.activeScenario]} /></>}
              {view.scenarioStack.length > 0 && <><p className="field-label">Стек</p><ScenarioList items={view.scenarioStack} /></>}
              {view.pendingScenarios.length > 0 && <><p className="field-label">Ожидают</p><ScenarioList items={view.pendingScenarios} /></>}
            </section>
          )}
          {view.slots.length > 0 && (
            <section className="trace-section"><h3>Параметры</h3>
              <dl className="key-values">{view.slots.map(({ key, value }) => (
                <div key={key}><dt>{key}</dt><dd>{value}</dd></div>
              ))}</dl>
            </section>
          )}
          {view.actions.length > 0 && (
            <section className="trace-section"><h3>Действия</h3>
              <ul className="plain-list">{view.actions.map((action, index) => <li key={`${action}-${index}`}>{action}</li>)}</ul>
            </section>
          )}
          {view.clarification && <section className="trace-section"><h3>Уточнение</h3><p>{view.clarification}</p></section>}
          {view.handoff && (
            <section className="trace-section"><h3>Передача оператору</h3>
              {view.handoff.queue && <p><span className="field-label">Очередь:</span> {view.handoff.queue}</p>}
              {view.handoff.reason && <p><span className="field-label">Причина:</span> {view.handoff.reason}</p>}
              {view.handoff.summary && <p><span className="field-label">Контекст:</span> {view.handoff.summary}</p>}
            </section>
          )}
          {view.latency.length > 0 && (
            <section className="trace-section"><h3>Задержки</h3>
              <dl className="latency-list">{view.latency.map(({ label, value, source }) => (
                <div key={label}><dt>{label}{source === 'browser' && <span className="source-note"> · браузер</span>}</dt><dd>{value}</dd></div>
              ))}</dl>
            </section>
          )}
        </>
      )}
    </aside>
  );
}
