"""Optional local wrapper; the packaged backend owns the versioned synthetic dataset."""

from app.analytics.demo import anomaly_events, seed_cli, synthetic_events  # noqa: F401

if __name__ == "__main__":
    seed_cli()
