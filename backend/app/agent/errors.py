"""Safe, actionable router failures; provider payloads never become API messages."""


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
    def __init__(self) -> None:
        super().__init__(
            "router_invalid_output",
            "The routing provider returned an invalid decision; "
            "please retry or contact an operator.",
        )
