from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.core.contracts import Contract, Language, Slots

Confidence = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]


class ScenarioScore(Contract):
    scenario_id: str = Field(min_length=1)
    confidence: Confidence


class ScenarioSelection(ScenarioScore):
    reason: str = Field(min_length=1, max_length=500)


class SemanticSegment(ScenarioSelection):
    text: str = Field(min_length=1)
    depends_on: list[int] | None = None


class RouterDecision(Contract):
    language: Language
    response_language: Literal["ru", "kk"] | None = None
    clarification_question: str | None = Field(default=None, min_length=1, max_length=400)
    segments: list[SemanticSegment] = Field(default_factory=list)
    scenarios: list[ScenarioSelection] = Field(min_length=1)
    alternatives: list[ScenarioScore] = Field(default_factory=list)
    slots: Slots = Field(default_factory=dict)
    is_continuation: bool = False

    @model_validator(mode="after")
    def validate_segments(self) -> "RouterDecision":
        ids = [item.scenario_id for item in self.scenarios]
        if len(ids) != len(set(ids)):
            raise ValueError("Selected scenarios must be unique")
        for index, segment in enumerate(self.segments):
            if segment.scenario_id not in ids:
                raise ValueError("Each segment must reference a selected scenario")
            if any(
                dependency < 0 or dependency >= index for dependency in segment.depends_on or []
            ):
                raise ValueError("depends_on uses zero-based earlier segment indices")
        return self


class ExtractedSlot(Contract):
    """Closed SDK schema: named values instead of an open JSON object."""

    name: str
    value: str | int | float | bool | list[str] | None


class RouterAgentOutput(Contract):
    """SDK transport schema; adapter restores the starter-kit slots object."""

    language: Language
    response_language: Literal["ru", "kk"] | None = None
    clarification_question: str | None = Field(default=None, min_length=1, max_length=400)
    segments: list[SemanticSegment]
    scenarios: list[ScenarioSelection]
    alternatives: list[ScenarioScore]
    slots: list[ExtractedSlot]
    is_continuation: bool

    def to_decision(self) -> RouterDecision:
        names = [slot.name for slot in self.slots]
        if len(names) != len(set(names)):
            raise ValueError("Extracted slot names must be unique")
        return RouterDecision(
            language=self.language,
            response_language=self.response_language,
            clarification_question=self.clarification_question,
            segments=self.segments,
            scenarios=self.scenarios,
            alternatives=self.alternatives,
            slots={slot.name: slot.value for slot in self.slots},
            is_continuation=self.is_continuation,
        )
