"""Mask authentication values without asking for or retaining them."""

import re

SECRET_LABEL = (
    r"(?:otp|sms[\s-]*код|смс[\s-]*код|код(?:\s+(?:из|от|в))?\s+(?:sms|смс)|"
    r"растау\s*коды|pin|пин|cvv|cvc|парол\w*|password|құпия\s?сөз\w*|"
    r"секретный\s+ответ|security\s+answer|код(?=\s*[:=]?\s*\d{4,8}(?!\d)))"
)
_NUMBER = re.compile(
    rf"(?P<label>{SECRET_LABEL})(?P<gap>[^\d\n\[]{{0,35}})(?P<value>\d(?:[\s-]*\d){{2,7}})(?!\d)",
    re.I,
)
_TOKEN = re.compile(rf"(?P<label>{SECRET_LABEL})(?P<gap>\s*[:=]\s*)(?P<value>(?!\[)\S+)", re.I)
_PASSWORD = re.compile(
    r"(?P<label>(?:мой\s+пароль|пароль\s+(?:это|был)|менің\s+құпиясөзім|my\s+password))"
    r"(?P<gap>\s*[:=]?\s+)(?P<value>(?!\[)\S+)",
    re.I,
)
_EXPOSED = re.compile(
    rf"(?P<label>(?:сообщил\w*|назвал\w*|передал\w*|продиктовал\w*|айттым|бердім)"
    rf"\s+(?:им\s+)?{SECRET_LABEL})(?P<gap>\s+)(?P<value>(?!\[)\S+)",
    re.I,
)
_CARD = re.compile(r"(?<!\d)(?:\d[\s-]*){13,19}(?!\d)")
_API_KEY = re.compile(r"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{30,}")
_DIGIT_WORD = (
    r"(?:ноль|нуль|один|два|три|четыре|пять|шесть|семь|восемь|девять|"
    r"нөл|бір|екі|үш|төрт|бес|алты|жеті|сегіз|тоғыз)"
)
_SPOKEN = re.compile(
    rf"(?P<label>{SECRET_LABEL})(?P<gap>\s*[:=]?\s+)(?P<value>{_DIGIT_WORD}(?:[\s,-]+{_DIGIT_WORD}){{2,7}})\b",
    re.I,
)


def redact_authentication(text: str, pending_question=None) -> str:
    for pattern in (_TOKEN, _PASSWORD, _NUMBER, _SPOKEN, _EXPOSED):
        text = pattern.sub(lambda m: m["label"] + m["gap"] + "[секрет скрыт]", text)
    if pending_question in ("exposure", "link_exposure"):
        text = re.sub(r"(?<!\d)\d{3,8}(?!\d)", "[секрет скрыт]", text)
    return _API_KEY.sub("[секрет скрыт]", _CARD.sub("[номер карты скрыт]", text))


def redact_risk_input(text: str) -> str:
    text = redact_authentication(text)
    text = re.sub(r"(?<!\d)(?:\+?\d[\s()-]*){10,12}(?!\d)", "[номер скрыт]", text)
    text = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "[контакт скрыт]", text)
    return re.sub(r"https?://\S+", "[ссылка]", text, flags=re.I)
