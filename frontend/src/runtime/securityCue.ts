// Candidate gate only. The server policy supplies precaution text; only Risk Agent
// supplies assessments. This never selects an assistant or creates another user turn.
export function mayNeedPrecaution(text: string): boolean {
  return /sms|смс|\bкод|pin|пин|cvv|cvc|парол|password|құпиясөз|растау|ссылк|сілтем|remote|удал[её]нн|anydesk|teamviewer|қашықтан|безопасн.*сч[её]т|қауіпсіз.*шот|неизвест.*(?:операци|перевод)|потер.*карт|укра.*карт|жоғал.*карт|карт.*жоғал/iu.test(text);
}
