from typing import Annotated

from pydantic import Field

from app.core.contracts import Contract

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ScenarioScore(Contract):
    scenario_id: str = Field(min_length=1)
    confidence: Confidence


class ScenarioSelection(ScenarioScore):
    reason: str = Field(min_length=1, max_length=500)
