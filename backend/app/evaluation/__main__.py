import argparse

from app.core.config import Settings
from app.data.loaders import load_starter_kit


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local Voice Router starter-kit inputs")
    parser.add_argument("--check-data", action="store_true", required=True)
    parser.parse_args()
    kit = load_starter_kit(Settings().starter_kit_path)
    print(
        f"Validated {len(kit.scenarios.scenarios)} scenarios, "
        f"{len(kit.scenarios.system_intents)} system intents, "
        f"{len(kit.actions.actions)} actions, {len(kit.dev_utterances.utterances)} dev utterances. "
        "Router evaluation was not run."
    )


if __name__ == "__main__":
    main()
