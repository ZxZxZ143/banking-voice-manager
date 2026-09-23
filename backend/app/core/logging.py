import logging


def configure_logging() -> None:
    """Log operational events only; never transcripts, credentials or full payloads."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
