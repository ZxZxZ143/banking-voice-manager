from functools import lru_cache, reduce
from operator import or_
from typing import Annotated, Literal

from pydantic import Field, StrictBool, StrictInt, create_model, model_validator

from app.core.contracts import Contract, Language, Slots
from app.packs.insurance_manager.data.models import SlotDataset
from app.tracing.selections import ScenarioScore, ScenarioSelection


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
    conversation_signal: Literal["none", "greeting", "answer", "partial_answer"] = "none"
    scope_kind: Literal["none", "small_talk", "identity", "banking", "unrelated"] = Field(
        default="none", exclude_if=lambda v: v == "none"
    )

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
    value: str | int | float | bool | list[str]


class RouterAgentOutput(Contract):
    """SDK transport schema; adapter restores the starter-kit slots object."""

    language: Language
    response_language: Literal["ru", "kk"] | None = None
    clarification_question: str | None = Field(default=None, min_length=1, max_length=400)
    segments: list[SemanticSegment] = Field(min_length=1)
    scenarios: list[ScenarioSelection] = Field(min_length=1)
    alternatives: list[ScenarioScore] = Field(max_length=2)
    slots: list[ExtractedSlot]
    is_continuation: bool
    conversation_signal: Literal["none", "greeting", "answer", "partial_answer"] = "none"
    scope_kind: Literal["none", "small_talk", "identity", "banking", "unrelated"] = "none"

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
            conversation_signal=self.conversation_signal,
            scope_kind=self.scope_kind,
        )


def source_output_type(slots: SlotDataset | None) -> type[RouterAgentOutput]:
    """Constrain SDK extraction by the same catalog validated by the business boundary."""
    return _source_output_type(slots.model_dump_json()) if slots else RouterAgentOutput


@lru_cache(maxsize=4)
def _source_output_type(serialized: str) -> type[RouterAgentOutput]:
    variants = []
    for slot in SlotDataset.model_validate_json(serialized).slots:
        string_value = Annotated[str, Field(min_length=1, pattern=slot.pattern)]
        value_type = (
            Literal[tuple(slot.values)]
            if slot.type == "enum"
            else StrictInt
            if slot.type == "integer"
            else StrictBool
            if slot.type == "boolean"
            else Annotated[list[string_value], Field(min_length=1)]
            if slot.type == "list"
            else Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")]
            if slot.type == "date"
            else string_value
        )
        variants.append(
            create_model(
                "SourceSlot_" + slot.name,
                __base__=Contract,
                name=(Literal[slot.name], ...),
                value=(value_type, Field(description=slot.description)),
            )
        )
    return create_model(
        "SourceRouterAgentOutput",
        __base__=RouterAgentOutput,
        slots=(list[reduce(or_, variants)], ...),
    )
