"""Local silence profiles with a bounded stability guard, never regex-only commit."""

from time import monotonic

from app.speech.structured.capture import recognize_context
from app.speech.structured.correction import parse_confirmation


class AdaptiveEndpoint:
    def __init__(self, context, *, clock=monotonic):
        self.context = context
        self.clock = clock
        self.profile = (
            "confirmation"
            if context.confirmation_kind != "none"
            else "region"
            if context.expected_kind == "region_code"
            else "identifier"
            if context.expected_kind != "none"
            else "ordinary"
        )
        self.base_ms = {"confirmation": 750, "region": 900, "identifier": 1300, "ordinary": 1600}[
            self.profile
        ]
        self._key = None
        self._since = None
        self._short_ms = self.base_ms

    def observe(self, text):
        key = None
        short = self.base_ms
        if self.profile == "confirmation":
            response = parse_confirmation(text, self.context.confirmation_kind)
            self.base_ms = 900 if response.kind == "correction" else 750
            short = self.base_ms
            if response.kind in {"confirm", "reject"}:
                key, short = response.kind, 650
            elif response.kind == "correction" and response.correction.new_fragment:
                key, short = response.correction, 800
        elif self.profile in {"region", "identifier"}:
            parsed = recognize_context(text, self.context)
            if parsed.accepted:
                key = (parsed.kind, parsed.value)
                short = 750 if self.profile == "region" else 1100
        if key != self._key:
            self._since = self.clock() if key is not None else None
        self._key, self._short_ms = key, short

    @property
    def pause_ms(self):
        # A single transient valid partial does not shorten endpointing. Its exact
        # value must remain unchanged for >=400 ms AND local VAD must be silent.
        stable = self._since is not None and self.clock() - self._since >= 0.4
        return self._short_ms if stable else self.base_ms
