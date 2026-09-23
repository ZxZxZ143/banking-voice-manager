"""Models for the supplied JSON wrappers; nested business content stays intact."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue


class SourceModel(BaseModel):
    # Preserve additional business fields instead of silently discarding source data.
    model_config = ConfigDict(extra="allow")


class DatasetMeta(SourceModel):
    dataset: str
    version: str
    as_of_date: date


class LocalizedText(SourceModel):
    ru: str
    kk: str


class RoutingExclusion(SourceModel):
    condition: str
    use_instead: str


class ScenarioSlots(SourceModel):
    required: list[str]
    optional: list[str]


class Handoff(SourceModel):
    when: str
    queue: str


class ScenarioExamples(SourceModel):
    ru: list[str]
    kk: list[str]


class ResponseTemplates(SourceModel):
    opening: str
    closing: str


class Scenario(SourceModel):
    scenario_id: str = Field(min_length=1)
    slug: str
    name: str
    domain: str
    category: str
    description: str
    not_this_if: list[RoutingExclusion]
    priority: Literal["normal", "high", "urgent"]
    fast_path_eligible: bool
    requires_identification: bool
    slots: ScenarioSlots
    actions: list[str]
    requires_confirmation: bool
    handoff: Handoff | None
    examples: ScenarioExamples
    responses: dict[Literal["ru", "kk"], ResponseTemplates]


class SystemIntent(SourceModel):
    id: str = Field(min_length=1)
    description: str
    behavior: str
    response: LocalizedText


class ScenarioDataset(SourceModel):
    meta: DatasetMeta
    scenarios: list[Scenario] = Field(min_length=1)
    system_intents: list[SystemIntent] = Field(min_length=1)


class SlotDefinition(SourceModel):
    name: str = Field(min_length=1)
    type: Literal["string", "enum", "integer", "date", "boolean", "list", "text"]
    description: str
    pattern: str | None = None
    values: list[str | int] | None = None
    prompt: LocalizedText


class SlotDataset(SourceModel):
    meta: DatasetMeta
    slots: list[SlotDefinition] = Field(min_length=1)


class ActionDefinition(SourceModel):
    name: str = Field(min_length=1)
    description: str
    # The starter kit uses alternatives such as "phone|iin", not JSON Schema.
    inputs: list[str]
    outputs: list[str]
    errors: list[str]
    irreversible: bool


class ActionDataset(SourceModel):
    meta: DatasetMeta
    queues: list[str]
    error_format: dict[str, JsonValue]
    error_codes: dict[str, str]
    error_handling: list[str]
    actions: list[ActionDefinition] = Field(min_length=1)


class KnowledgeDataset(SourceModel):
    meta: DatasetMeta
    company: dict[str, JsonValue]
    offices: list[dict[str, JsonValue]]
    inspection_points: list[dict[str, JsonValue]]
    products: dict[str, dict[str, JsonValue]]
    clinics: list[dict[str, JsonValue]]
    claims: dict[str, JsonValue]
    payments: dict[str, JsonValue]
    cancellation: dict[str, JsonValue]
    bonus_malus: dict[str, JsonValue]
    app_help: dict[str, JsonValue]
    fraud_policy: list[str]
    documents_available: dict[str, str]
    complaints: dict[str, JsonValue]


class ClientRecord(SourceModel):
    client_id: str
    full_name: str
    phone: str
    iin: str
    city: str
    email: str
    address: str
    bm_class: str
    preferred_language: Literal["ru", "kk"]


class PolicyRecord(SourceModel):
    policy_number: str
    client_id: str
    product: str
    start_date: date
    end_date: date
    premium: int | None
    details: dict[str, JsonValue]


class ClaimRecord(SourceModel):
    claim_number: str
    client_id: str
    policy_number: str
    claim_type: str
    incident_date: date
    status: str
    next_step: str


class PaymentRecord(SourceModel):
    payment_id: str
    client_id: str
    date: date
    amount: int
    product: str
    status: str
    policy_number: str | None


class MockBackendDataset(SourceModel):
    meta: DatasetMeta
    defaults: dict[str, JsonValue]
    clients: list[ClientRecord]
    policies: list[PolicyRecord]
    claims: list[ClaimRecord]
    payments: list[PaymentRecord]


class SampleAction(SourceModel):
    name: str
    mode: Literal["preview", "execute"] | None = None
    result: dict[str, JsonValue] | None = None
    queue: str | None = None
    topic: str | None = None


class SampleTurn(SourceModel):
    role: Literal["client", "bot"]
    text: str
    lang: Literal["ru", "kk", "mixed"]
    scenarios: list[str] = Field(default_factory=list)
    slots: dict[str, JsonValue] = Field(default_factory=dict)
    actions: list[SampleAction] = Field(default_factory=list)


class SampleDialog(SourceModel):
    dialog_id: str
    title: str
    tags: list[str]
    client_id: str | None
    turns: list[SampleTurn]


class DialogDataset(SourceModel):
    meta: DatasetMeta
    dialogs: list[SampleDialog]


class DevUtterance(SourceModel):
    id: str
    text: str
    lang: Literal["ru", "kk", "mixed"]
    expected: list[str] = Field(min_length=1)
    type: Literal["single", "multi_intent", "out_of_scope", "unclear"]


class DevDataset(SourceModel):
    meta: DatasetMeta
    utterances: list[DevUtterance]
