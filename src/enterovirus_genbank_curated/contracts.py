"""Repository contract validation used before the build pipeline exists."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECISION_COLUMNS = (
    "decision_id",
    "decision_type",
    "subject_key",
    "accession",
    "field_name",
    "new_value",
    "reason",
    "evidence_reference",
    "confirmed_by",
    "source_artifact",
    "status",
    "effective_from",
    "effective_through",
    "notes",
)

DECISION_ID_RE = re.compile(r"^D-[0-9a-f]{12,64}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALLOWED_DECISION_STATUSES = frozenset({"active", "superseded", "retired"})
EXPECTED_BASELINE_COUNTS = {
    "source_records": 25727,
    "canonical_rows": 24546,
    "vouched_rows": 10086,
    "provisional_rows": 14460,
    "manual_decisions": 2753,
    "rules": 25,
}


class ContractError(ValueError):
    """Raised when a repository contract is invalid."""


@dataclass(frozen=True)
class LedgerSummary:
    rows: int
    active_rows: int


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON contract must contain an object: {path}")
    return value


def validate_schema_document(path: Path, *, required_title: str) -> None:
    schema = load_json(path)
    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ContractError(f"{path} must use JSON Schema draft 2020-12")
    if schema.get("title") != required_title:
        raise ContractError(f"{path} title must be {required_title!r}")
    if schema.get("type") != "object":
        raise ContractError(f"{path} root type must be object")
    if schema.get("additionalProperties") is not False:
        raise ContractError(f"{path} must reject undeclared properties")
    required = schema.get("required")
    properties = schema.get("properties")
    if not isinstance(required, list) or not required:
        raise ContractError(f"{path} must declare required properties")
    if not isinstance(properties, dict):
        raise ContractError(f"{path} must declare properties")
    missing = set(required) - set(properties)
    if missing:
        raise ContractError(f"{path} requires undeclared properties: {sorted(missing)}")


def validate_parity_spec(path: Path) -> None:
    spec = load_json(path)
    if spec.get("contract_version") != 1:
        raise ContractError("parity contract_version must be 1")
    if spec.get("baseline_release") != "2.1.5":
        raise ContractError("parity baseline_release must be 2.1.5")

    counts = spec.get("expected_counts")
    if counts != EXPECTED_BASELINE_COUNTS:
        raise ContractError(
            f"parity counts differ from the frozen baseline: {counts!r}"
        )

    raw = spec.get("raw_input")
    if not isinstance(raw, dict):
        raise ContractError("parity raw_input must be an object")
    for key in ("archive_sha256", "uncompressed_sha256"):
        if not SHA256_RE.fullmatch(str(raw.get(key, ""))):
            raise ContractError(f"parity raw_input.{key} must be a lowercase SHA-256")
    if raw.get("record_count") != EXPECTED_BASELINE_COUNTS["source_records"]:
        raise ContractError("parity raw record_count does not match source_records")

    artifacts = spec.get("expected_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("parity expected_artifacts must be a non-empty list")
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ContractError("each parity artifact must be an object")
        artifact_path = artifact.get("path")
        if not isinstance(artifact_path, str) or not artifact_path.startswith("final/"):
            raise ContractError(f"invalid parity artifact path: {artifact_path!r}")
        if artifact_path in seen_paths:
            raise ContractError(f"duplicate parity artifact path: {artifact_path}")
        seen_paths.add(artifact_path)
        if artifact.get("hash_scope") not in {"file_bytes", "logical_content"}:
            raise ContractError(f"invalid hash_scope for {artifact_path}")
        if not SHA256_RE.fullmatch(str(artifact.get("sha256", ""))):
            raise ContractError(f"invalid SHA-256 for {artifact_path}")

    policy = spec.get("policy")
    if not isinstance(policy, dict):
        raise ContractError("parity policy must be an object")
    if policy.get("existing_final_is_pipeline_input") is not False:
        raise ContractError("existing final/ must never be a pipeline input")
    if policy.get("baseline_release_mutable") is not False:
        raise ContractError("the 2.1.5 baseline must be immutable")


def validate_decision_ledger(path: Path) -> LedgerSummary:
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ContractError(f"cannot read decision ledger {path}: {exc}") from exc

    with handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if tuple(reader.fieldnames or ()) != DECISION_COLUMNS:
            raise ContractError(
                "decision ledger columns must exactly match the documented contract"
            )

        seen_ids: set[str] = set()
        seen_active_assertions: set[tuple[str, str]] = set()
        previous_sort_key: tuple[str, str, str, str] | None = None
        rows = 0
        active_rows = 0

        for line_number, row in enumerate(reader, start=2):
            rows += 1
            decision_id = row["decision_id"]
            if not DECISION_ID_RE.fullmatch(decision_id):
                raise ContractError(f"line {line_number}: invalid decision_id {decision_id!r}")
            if decision_id in seen_ids:
                raise ContractError(f"line {line_number}: duplicate decision_id {decision_id}")
            seen_ids.add(decision_id)

            for field in ("decision_type", "subject_key", "field_name", "new_value"):
                if not row[field].strip():
                    raise ContractError(f"line {line_number}: {field} must not be blank")

            status = row["status"]
            if status not in ALLOWED_DECISION_STATUSES:
                raise ContractError(f"line {line_number}: invalid status {status!r}")

            sort_key = (
                row["decision_type"],
                row["subject_key"],
                row["field_name"],
                decision_id,
            )
            if previous_sort_key is not None and sort_key < previous_sort_key:
                raise ContractError(
                    f"line {line_number}: ledger is not in deterministic sort order"
                )
            previous_sort_key = sort_key

            if status == "active":
                active_rows += 1
                assertion_key = (row["subject_key"], row["field_name"])
                if assertion_key in seen_active_assertions:
                    raise ContractError(
                        "line "
                        f"{line_number}: duplicate active assertion for {assertion_key!r}"
                    )
                seen_active_assertions.add(assertion_key)

    return LedgerSummary(rows=rows, active_rows=active_rows)


def validate_contracts(repository_root: Path) -> None:
    validate_schema_document(
        repository_root / "registry/schemas/decisions.schema.json",
        required_title="Curation decision record",
    )
    validate_schema_document(
        repository_root / "registry/schemas/rules.schema.json",
        required_title="Deterministic curation rule",
    )
    validate_parity_spec(repository_root / "releases/2.1.5/parity.json")
