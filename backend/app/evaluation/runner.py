import json
from pathlib import Path

from app.agent.router import Router
from app.data.models import DevDataset
from app.dialog.models import DialogState


async def generate_predictions(dataset: DevDataset, router: Router) -> dict[str, list[str]]:
    """Do not pass expected labels to the router; abort on failure instead of fabricating output."""
    predictions: dict[str, list[str]] = {}
    for utterance in dataset.utterances:
        decision = await router.route(utterance.text, DialogState(session_id=utterance.id))
        predictions[utterance.id] = [item.scenario_id for item in decision.scenarios]
    return predictions


def write_predictions(predictions: dict[str, list[str]], path: Path) -> None:
    """Exclusive creation protects previous runs from accidental overwrite."""
    with path.open("x", encoding="utf-8") as output:
        json.dump(predictions, output, ensure_ascii=False, indent=2)
        output.write("\n")
