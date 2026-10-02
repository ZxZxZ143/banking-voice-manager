type Data = Record<string, unknown>;
import { isSalesPack } from '../../types/agent.ts';
const record = (value: unknown): Data | null =>
  typeof value === 'object' && value !== null && !Array.isArray(value) ? value as Data : null;
const text = (value: unknown): string | null => typeof value === 'string' && value.trim() ? value : null;
const texts = (value: unknown): string[] => Array.isArray(value)
  ? value.flatMap(v => text(v) ? [v as string] : []) : [];

export function createSalesLeadView(state: unknown) {
  const data = record(state);
  const lead = record(data?.sales_lead);
  if (!isSalesPack(data?.scenario_mode) || !lead || !text(lead.outcome)) return null;
  const preferences = record(lead.customer_preferences);
  return {
    outcome: text(lead.outcome), category: text(lead.product_category),
    selected: text(lead.selected_product_id), interest: text(lead.interest_level),
    nextAction: text(lead.next_action), presented: texts(lead.presented_products),
    compared: texts(lead.compared_products), objections: texts(lead.objections),
    preferences: preferences ? Object.entries(preferences)
      .filter(([, v]) => typeof v === 'string' || typeof v === 'boolean'
        || (typeof v === 'number' && Number.isFinite(v)))
      .map(([key, value]) => ({ key, value: String(value) })) : [],
  };
}
