// Mask volunteered authentication values before history, API requests or voice diagnostics.
// Ordinary phones/IIN remain usable by the Insurance identification flow.
export function redactAuthentication(text: string, pendingQuestion?: unknown): string {
  const label = '(?:otp|sms[\\s-]*код|смс[\\s-]*код|код(?:\\s+(?:из|от|в))?\\s+(?:sms|смс)|растау\\s*коды|pin|пин|cvv|cvc|парол[а-я]*|password|құпия\\s?сөз[а-я]*|секретный\\s+ответ|код(?=\\s*[:=]?\\s*\\d{4,8}(?!\\d)))';
  const digitWord = '(?:ноль|нуль|один|два|три|четыре|пять|шесть|семь|восемь|девять|нөл|бір|екі|үш|төрт|бес|алты|жеті|сегіз|тоғыз)';
  const safe = text
    .replace(new RegExp(`(${label})(\\s*[:=]\\s*)(?!\\[)\\S+`, 'gi'), '$1$2[секрет скрыт]')
    .replace(/(мой пароль|пароль это|менің құпиясөзім|my password)(\s*[:=]?\s+)(?!\[)\S+/gi, '$1$2[секрет скрыт]')
    .replace(new RegExp(`(${label})([^\\d\\n\\[]{0,35})\\d(?:[\\s-]*\\d){2,7}(?!\\d)`, 'gi'), '$1$2[секрет скрыт]')
    .replace(new RegExp(`(${label})(\\s*[:=]?\\s+)${digitWord}(?:[\\s,-]+${digitWord}){2,7}(?![а-яәғқңөұүһі])`, 'gi'), '$1$2[секрет скрыт]')
    .replace(new RegExp(`((?:сообщил[а-я]*|назвал[а-я]*|передал[а-я]*|продиктовал[а-я]*|айттым|бердім)\\s+(?:им\\s+)?${label})(\\s+)(?!\\[)\\S+`, 'gi'), '$1$2[секрет скрыт]')
    .replace(/(?<!\d)(?:\d[\s-]*){13,19}(?!\d)/g, '[номер карты скрыт]')
    .replace(/sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}/g, '[секрет скрыт]');
  return pendingQuestion === 'exposure' || pendingQuestion === 'link_exposure'
    ? safe.replace(/(?<!\d)\d{3,8}(?!\d)/g, '[секрет скрыт]') : safe;
}
