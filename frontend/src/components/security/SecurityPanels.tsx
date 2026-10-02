import { actionNames, createFraudCaseView, createRiskView, signalNames } from './securityViewModel';

export function RiskPanel({ risk }: { risk: unknown }) {
  const view = createRiskView(risk);
  return <section className="panel" aria-label="Risk Intelligence">
    <h2>Risk Intelligence</h2>
    {!view ? <p className="muted">На этой реплике оценка риска не требуется.</p>
      : <>
        <strong>{view.status === 'analyzed' ? view.level.toUpperCase() : 'Оценка недоступна'}</strong>
        {view.signals.length > 0 && <ul>{view.signals.map(s => <li key={s}>{signalNames[s]}</li>)}</ul>}
        {view.action && view.status === 'analyzed' && <p>{actionNames[view.action]}</p>}
      </>}
    <p className="muted">Оценка помогает выбрать меры предосторожности. Она не подтверждает мошенничество и не меняет банковские операции.</p>
  </section>;
}

export function FraudCasePanel({ state }: { state: unknown }) {
  const view = createFraudCaseView(state);
  if (!view) return null;
  const labels: Record<string, string> = { open: 'Уточняем безопасные факты', informed: 'Рекомендации даны', needs_review: 'Нужна проверка специалистом' };
  return <section className="conversation-notice" aria-label="FraudCaseResult">
    <h3>FraudCaseResult</h3><strong>{labels[view.status]}</strong>
    {view.facts.length > 0 && <ul>{view.facts.map(s => <li key={s}>{signalNames[s]}</li>)}</ul>}
    {view.transaction && <p>{view.transaction === 'transfer' ? 'Перевод' : 'Покупка по карте'}</p>}
    {view.handoff && <p>Передача оператору</p>}
  </section>;
}
