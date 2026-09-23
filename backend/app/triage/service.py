from time import perf_counter

from app.core.contracts import Language
from app.triage.models import TriageResult


class TriageService:
    def prepare(self, text: str, language_hint: Language | None = None) -> TriageResult:
        """Trim whitespace only; language and spoken-value normalization are future work."""
        started = perf_counter()
        return TriageResult(
            original_text=text,
            text=text.strip(),
            language=language_hint,
            latency_ms=(perf_counter() - started) * 1000,
        )
