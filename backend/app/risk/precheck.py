"""Candidate gate only. Regexes do not conclude that fraud occurred."""

import re
from dataclasses import dataclass

from app.risk.models import Guidance

PATTERNS = tuple(
    re.compile(p, re.I)
    for p in (
        r"otp|sms|смс|\bкод\w*|pin|пин|cvv|cvc|парол|password|құпия\s?сөз|растау",
        r"ссылк|фишинг|phish|сілтем|https?://",
        r"удал[её]нн\w*\s+доступ|remote|anydesk|teamviewer|қашықтан",
        r"безопасн\w*\s+сч[её]т|safe\s+account|қауіпсіз\s+шот",
        r"(?:звон|позвон|қоңырау|якобы|представил).*банк|банк.*(?:звон|қоңырау)",
        r"(?:\bне\b|неизвест|чуж|бейтаныс|жасама|жоқ).*(?:перевод|плат[её]ж|покуп|транзак|операци|аудар|төлем)",
        r"(?:перевод|плат[её]ж|покуп|аудар|төлем).*(?:не\s+я|не\s+соверш|не\s+делал|жасама|жоқ)",
        r"(?:потер|укра|жоғал|ұрла).*(?:карт)|(?:аккаунт|профил|шот|номер|нөмір).*(?:взлом|чуж|смен|өзгерт|бұз)",
        r"карт.*(?:потер|укра|жоғал|ұрла)|(?:взлом|бұз).*(?:аккаунт|профил|шот)",
        r"(?:мошенн|алаяқ|давлен|қысым|взлом|бұзыл)",
    )
)


@dataclass(frozen=True)
class RiskCandidate:
    analyze: bool
    immediate_guidance: tuple[Guidance, ...] = ()


def precheck(text: str, *, security_followup=False) -> RiskCandidate:
    candidate = security_followup or any(p.search(text) for p in PATTERNS)
    hints = []
    request = re.search(r"прос|просят|треб|сообщ|назв|продикт|айт|сұра|берді|жіберді", text, re.I)
    if request and PATTERNS[0].search(text):
        hints.append("do_not_share_secrets")
    if PATTERNS[1].search(text) and re.search(r"подозр|suspicious|күмән|бейтаныс", text, re.I):
        hints.append("avoid_link")
    if PATTERNS[2].search(text) and request:
        hints.append("avoid_remote_access")
    if PATTERNS[3].search(text):
        hints.append("no_safe_account_transfer")
    if re.search(r"неизвест|не\s+(?:делал|совершал)|жасама|бейтаныс", text, re.I) and re.search(
        r"перевод|покуп|плат[её]ж|операци|аудар|төлем", text, re.I
    ):
        hints.append("transaction_review")
    if re.search(r"потер|укра|жоғал|ұрла", text, re.I) and re.search(r"карт", text, re.I):
        hints.append("card_review")
    return RiskCandidate(bool(candidate), tuple(hints))
