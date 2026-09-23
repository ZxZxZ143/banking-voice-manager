"""Safe, application-level speech failures without request payloads."""


class SpeechConfigurationError(RuntimeError):
    """A speech provider is not configured for use."""


class SpeechProviderError(RuntimeError):
    """A speech provider failed to return a usable result."""
