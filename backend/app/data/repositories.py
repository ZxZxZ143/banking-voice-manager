"""Read-only copies of already-loaded knowledge and synthetic backend data."""

from copy import deepcopy
from typing import Literal

from pydantic import JsonValue

from app.data.models import KnowledgeDataset, MockBackendDataset


class KnowledgeRepository:
    def __init__(self, dataset: KnowledgeDataset) -> None:
        self._data = dataset.model_dump(mode="json")

    def get_all(self) -> dict[str, JsonValue]:
        return deepcopy(self._data)

    def get(self, topic: str) -> JsonValue:
        """Resolve an exact dotted key, e.g. payments.installments; not semantic search."""
        current = self._data
        for key in topic.split("."):
            if not key or not isinstance(current, dict) or key not in current:
                raise KeyError(topic)
            current = current[key]
        return deepcopy(current)


CollectionName = Literal["clients", "policies", "claims", "payments"]


class MockBackendRepository:
    def __init__(self, dataset: MockBackendDataset) -> None:
        self._data = dataset.model_dump(mode="json")

    def get_all(self, collection: CollectionName) -> list[dict[str, JsonValue]]:
        if collection not in {"clients", "policies", "claims", "payments"}:
            raise ValueError(f"Unknown backend collection: {collection}")
        return deepcopy(self._data[collection])

    def find(self, collection: CollectionName, **filters: JsonValue) -> list[dict[str, JsonValue]]:
        """Exact top-level matches, returning copies; no updates or invented records."""
        return [
            record
            for record in self.get_all(collection)
            if all(key in record and record[key] == value for key, value in filters.items())
        ]

    def get_defaults(self) -> dict[str, JsonValue]:
        return deepcopy(self._data["defaults"])
