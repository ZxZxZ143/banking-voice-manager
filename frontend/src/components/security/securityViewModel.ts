type Data = Record<string, unknown>;
const record = (v: unknown): Data | null => typeof v === 'object' && v !== null && !Array.isArray(v) ? v as Data : null;
const enums = (v: unknown, allowed: readonly string[]): string | null => typeof v === 'string' && allowed.includes(v) ? v : null;

export const signalNames: Record<string, string> = {
  bank_impersonation: 'Звонящий представился банком', otp_requested_by_third_party: 'Третье лицо просит код',
  otp_disclosed: 'Код уже сообщён', credential_disclosed: 'Секретные данные раскрыты',
  pin_or_password_requested: 'Просят PIN или пароль', cvv_requested: 'Просят CVV',
  suspicious_link: 'Подозрительная ссылка', remote_access_requested: 'Просят удалённый доступ',
  remote_access_installed: 'Удалённый доступ установлен', unknown_transaction: 'Неизвестная операция',
  account_takeover_concern: 'Подозрение на чужой доступ', unauthorized_contact_change: 'Контакт изменён без согласия',
  transfer_under_pressure: 'Перевод под давлением', lost_stolen_card: 'Карта потеряна или украдена',
  coerced_transfer_sent: 'Перевод под давлением уже выполнен',
};
export const actionNames: Record<string, string> = {
  none: 'Нет рекомендации', show_security_guidance: 'Советы по безопасности',
  security_review: 'Проверка специалистом', urgent_security_review: 'Срочная проверка специалистом',
  operator_handoff: 'Передача оператору',
};
const list = (v: unknown) => Array.isArray(v) ? [...new Set(v.filter((s): s is string => typeof s === 'string' && Object.hasOwn(signalNames, s)))] : [];

export function createRiskView(value: unknown) {
  const data = record(value);
  const level = enums(data?.level, ['none', 'low', 'medium', 'high', 'critical']);
  const status = enums(data?.analysis_status, ['analyzed', 'unavailable', 'invalid_output']);
  if (!data || !level || !status) return null;
  const action = enums(data.recommended_action, Object.keys(actionNames));
  return { level, status, signals: list(data.signals), action, relevant: data.risk_relevant === true };
}

export function createFraudCaseView(value: unknown) {
  const state = record(value), data = record(state?.fraud_case);
  if (state?.scenario_mode !== 'fraud_security' || !data) return null;
  const status = enums(data.case_status, ['open', 'informed', 'needs_review']);
  const caseType = enums(data.case_type, ['none', 'social_engineering', 'transaction', 'phishing', 'remote_access', 'account_access', 'lost_card', 'credential_exposure']);
  if (!status || !caseType) return null;
  return { status, caseType, facts: list(data.facts), handoff: data.handoff === true,
    transaction: enums(data.transaction_kind, ['transfer', 'purchase']), risk: createRiskView(data.risk) };
}
