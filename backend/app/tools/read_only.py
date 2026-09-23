"""Exact, read-only access to the synthetic demo data; no authentication or writes."""

import re

from app.data.repositories import KnowledgeRepository, MockBackendRepository
from app.tools.actions import ToolResult


def find_client(
    repository: MockBackendRepository, *, phone: str | None = None, iin: str | None = None
) -> ToolResult:
    """Resolve one synthetic client; never accept an agent-supplied client_id as proof."""
    if not phone and not iin:
        return ToolResult.failure("invalid_input", "A phone number or IIN is required.")
    if (phone is not None and not re.fullmatch(r"\+7\d{10}", phone)) or (
        iin is not None and not re.fullmatch(r"\d{12}", iin)
    ):
        return ToolResult.failure("invalid_input", "The identifier format is invalid.")
    filters = {name: value for name, value in {"phone": phone, "iin": iin}.items() if value}
    matches = repository.find("clients", **filters)
    if len(matches) != 1:
        return ToolResult.failure(
            "not_found", "No unique synthetic client matches the identifiers."
        )
    return ToolResult(success=True, data={"client_id": matches[0]["client_id"]})


def get_policy(
    repository: MockBackendRepository, *, client_id: str, policy_number: str | None = None
) -> ToolResult:
    """Return minimal policy fields, restricted to a previously resolved client."""
    if not client_id or (
        policy_number is not None
        and not re.fullmatch(r"SQ-(OGPO|CASCO|TRVL|PROP|NS|DMS)-\d{6}", policy_number)
    ):
        return ToolResult.failure("invalid_input", "The policy identifier format is invalid.")
    matches = repository.find("policies", client_id=client_id)
    if policy_number is not None:
        matches = [record for record in matches if record["policy_number"] == policy_number]
    if not matches:
        # Ownership mismatch and an absent record intentionally have the same result.
        return ToolResult.failure("not_found", "No matching policy was found for this client.")
    if len(matches) != 1:
        return ToolResult.failure(
            "invalid_input", "A policy number is required to choose one policy."
        )
    return ToolResult(
        success=True,
        data={
            key: matches[0][key] for key in ("policy_number", "product", "start_date", "end_date")
        },
    )


def get_claim(
    repository: MockBackendRepository, *, client_id: str, claim_number: str | None = None
) -> ToolResult:
    """Return one owned claim; never infer ownership from its associated policy."""
    if not client_id:
        return ToolResult.failure("not_found", "No matching claim was found for this client.")
    matches = repository.find("claims", client_id=client_id)
    if claim_number is not None:
        matches = [record for record in matches if record["claim_number"] == claim_number]
    if len(matches) != 1:
        return ToolResult.failure(
            "not_found", "No unique matching claim was found for this client."
        )
    return ToolResult(
        success=True,
        data={key: matches[0][key] for key in ("claim_number", "status", "next_step")},
    )


def kb_lookup(repository: KnowledgeRepository, topic: str) -> ToolResult:
    """Return only an exact knowledge key, without inventing a missing answer."""
    try:
        answer = repository.get(topic)
    except KeyError:
        return ToolResult.failure("not_found", "This knowledge topic is unavailable.")
    return ToolResult(success=True, data={"answer": answer})
