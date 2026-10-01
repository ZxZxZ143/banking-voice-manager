import { createSalesLeadView } from './salesLeadViewModel';

export function SalesLeadPanel({ state }: { state: unknown }) {
  const lead = createSalesLeadView(state);
  if (!lead) return null;
  const data = typeof state === 'object' && state !== null ? state as Record<string, unknown> : null;
  const conditions = Array.isArray(data?.product_conditions) ? data.product_conditions.flatMap(value => {
    if (typeof value !== 'object' || !value) return [];
    const item = value as Record<string, unknown>;
    return typeof item.product_id === 'string' && typeof item.name === 'string' && typeof item.text === 'string'
      ? [{id: item.product_id, name: item.name, text: item.text}] : [];
  }) : [];
  return <section className="conversation-notice" aria-label="SalesLeadResult">
    <h3>SalesLeadResult · результат консультации</h3>
    <p className="muted">Демо: продукт не открыт, заявка и звонок не отправлены в банк.</p>
    <dl className="key-values">
      {Object.entries({ outcome: lead.outcome, category: lead.category, selected_product: lead.selected,
        interest: lead.interest, next_action: lead.nextAction, presented: lead.presented.join(', '),
        compared: lead.compared.join(', '), objections: lead.objections.join(', '),
      }).filter(([, v]) => v).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
      {lead.preferences.map(({ key, value }) => <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
    </dl>
    {conditions.map(product => <details key={product.id}>
      <summary>Полные условия · {product.name}</summary><p>{product.text}</p>
    </details>)}
  </section>;
}
