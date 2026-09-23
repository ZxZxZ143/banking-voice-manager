"""Safe, actionable router failures; provider payloads never become API messages."""

ROUTER_VALIDATION_REASONS = frozenset(
    {
        "invalid_structure",
        "unknown_scenario",
        "alternatives",
        "system_mix",
        "segment_coverage",
        "continuation",
        "unknown_slot",
        "invalid_slot",
    }
)


class RouterError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class RouterConfigurationError(RouterError):
    def __init__(self) -> None:
        super().__init__(
            "router_not_configured",
            "Configure OPENAI_API_KEY, OPENAI_ROUTER_MODEL and the starter-kit slot catalog.",
        )


class RouterProviderError(RouterError):
    def __init__(self, *, timeout: bool = False) -> None:
        super().__init__(
            "router_timeout" if timeout else "router_provider_error",
            "Routing timed out; please retry."
            if timeout
            else "Routing provider unavailable; check server credentials/model or retry later.",
        )


class RouterOutputError(RouterError):
    def __init__(self, validation_reason: str = "invalid_structure") -> None:
        self.validation_reason = (
            validation_reason
            if isinstance(validation_reason, str) and validation_reason in ROUTER_VALIDATION_REASONS
            else "invalid_structure"
        )
        super().__init__(
            "router_invalid_output",
            "The routing provider returned an invalid decision; "
            "please retry or contact an operator.",
        )
