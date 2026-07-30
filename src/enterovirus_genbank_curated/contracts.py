"""Repository contract *shape* validation, and the curation ledger's contract.

Two things are validated across two modules, and the split is load-bearing:

* *Contract shape* — here. The JSON Schemas and the active parity specification are well-formed,
  internally consistent, and declare nothing undeclared. **Nothing in this module reads `final/`.**
* *Baseline verification* — `oracle/release.py`. The parity specification actually describes the
  release that ships in this repository: hashes are recomputed, rows are counted, and the frozen raw
  archive is authenticated against the release's own build manifest.

Without the second half the parity contract would be self-certifying: a wrong hash or a wrong
row count would sit in the parity spec and never be contradicted by anything. It lives in `oracle/`
rather than here because `build.py` imports this module, so a release read on this side of the line
would be reachable from every build — which is the property `docs/pipeline.md` boundary 1 forbids.

The composed verb behind `evgc validate-contracts` is `oracle.release.validate_contracts`, which
calls `validate_contract_shape` below and then verifies the baseline.

The active baseline is **2.4.1**. `releases/2.1.5/parity.json` and `releases/2.3.0/parity.json`
are retained as the historical record of superseded public releases and are **no longer verified
against the tree** — there is only one `final/`, and once it holds 2.4.1 bytes a spec describing an
earlier release cannot be satisfied by it. Each retired release remains immutable in git history
(2.1.5 at `82f2966`; 2.3.0 at `edbacc6`..`134f899`, the four-commit refresh that retargeted it).

Which specs are retired is recorded in the paragraph above and nowhere in code. A
`HISTORICAL_PARITY_SPEC_PATHS` tuple used to carry the same list, read by nothing and documented as
read by nothing; it was removed on 2026-07-30. A constant that exists only to be prose is prose.

`BASELINE_RELEASE` below is a hardcoded literal on purpose, and `validate_parity_spec` compares
the spec against it rather than trusting the spec's own `baseline_release` field. Reading the
version out of the spec would make retargeting the oracle a data edit instead of a code edit,
which is the self-certification failure this module exists to prevent. Moving the baseline should
require changing this constant deliberately.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DECISIONS_SCHEMA_PATH = "registry/schemas/decisions.schema.json"
DECISIONS_LEDGER_PATH = "registry/decisions.tsv"
RULES_SCHEMA_PATH = "registry/schemas/rules.schema.json"
BASELINE_RELEASE = "2.4.1"
PARITY_SPEC_PATH = f"releases/{BASELINE_RELEASE}/parity.json"

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

LEDGER_SORT_COLUMNS = ("decision_type", "subject_key", "field_name", "decision_id")
ACTIVE_STATUS = "active"

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")

# Measured from the shipped 2.4.1 release, not derived from earlier figures. For the record:
# 2.1.5 shipped 25727 / 24546 / 10086 / 14460 / 2753 / 25; 2.3.0 shipped 25727 / 24301 / 10084 /
# 14217 / 2800 / 28 (245 canonical records removed between 2.1.5 and 2.3.0, none added, so
# source_records did not move). Neither 2.4.0 nor 2.4.1 changes any row in or out of the corpus or
# any sequence -- both are classification/origin/reference_label text edits on already-shipped
# records, so all four population counts here are identical to 2.3.0's. manual_decisions moves
# 2800 (2.3.0, last public baseline) -> 2912 (2.4.1): +97 from 2.4.0's 19-record K1-K3 fix (2.4.0
# itself was never a public baseline -- it shipped privately with a defective provenance stamp,
# see docs/decision-log.md in the private repo) and a further +15 from 2.4.1's own fix to 11 of
# those same records (3 regressed or left inconsistent by 2.4.0, plus the 2,643nt/JC0131xx twins
# it never touched).
EXPECTED_BASELINE_COUNTS = {
    "source_records": 25727,
    "canonical_rows": 24301,
    "vouched_rows": 10084,
    "provisional_rows": 14217,
    "manual_decisions": 2912,
    "rules": 28,
}

PARITY_TOP_LEVEL_KEYS = frozenset(
    {
        "contract_version",
        "baseline_release",
        "public_release_commit",
        "source_release_commit",
        "source_schema_version",
        "raw_input",
        "expected_counts",
        "expected_artifacts",
        "policy",
    }
)
PARITY_RAW_INPUT_KEYS = frozenset(
    {
        "path",
        "record_count",
        "archive_member",
        "archive_sha256",
        "uncompressed_bytes",
        "uncompressed_sha256",
    }
)
PARITY_ARTIFACT_KEYS = frozenset({"path", "hash_scope", "sha256"})
PARITY_POLICY_KEYS = frozenset(
    {
        "existing_final_is_pipeline_input",
        "baseline_release_mutable",
        "scientific_changes_require_explicit_review",
        "undeclared_external_inputs_allowed",
    }
)
HASH_SCOPES = frozenset({"file_bytes", "logical_content"})

# The prefix every parity artifact path must carry. This is the one place a build-side module names
# the release tree, and it names it as a string to validate rather than a path to open — see the
# exemption in `tests/test_module_boundaries.py`.
RELEASE_PATH_PREFIX = "final/"


class ContractError(ValueError):
    """Raised when a repository contract is invalid."""


@dataclass(frozen=True)
class LedgerSummary:
    rows: int
    active_rows: int


@dataclass(frozen=True)
class DecisionContract:
    """The ledger contract, derived from the JSON Schema rather than restated in code."""

    columns: tuple[str, ...]
    non_blank_columns: frozenset[str]
    patterns: tuple[tuple[str, re.Pattern[str]], ...]
    enums: tuple[tuple[str, frozenset[str]], ...]


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read JSON contract {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ContractError(f"JSON contract must contain an object: {path}")
    return value


def require_exact_keys(value: dict[str, Any], expected: frozenset[str], label: str) -> None:
    actual = set(value)
    missing = sorted(expected - actual)
    undeclared = sorted(actual - expected)
    if missing or undeclared:
        raise ContractError(f"{label}: missing keys {missing}, undeclared keys {undeclared}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ContractError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def validate_schema_document(path: Path, *, required_title: str) -> dict[str, Any]:
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
    return schema


def load_decision_contract(schema_path: Path) -> DecisionContract:
    """Derive the executable ledger contract from the published JSON Schema.

    The schema is the single source of truth for which columns exist, which must be non-blank,
    which are pattern-constrained, and which are enumerated. Restating any of that in Python
    would let the published schema and the enforced contract drift apart.
    """
    schema = validate_schema_document(schema_path, required_title="Curation decision record")
    properties: dict[str, Any] = schema["properties"]
    columns = tuple(schema["required"])
    if columns != DECISION_COLUMNS:
        raise ContractError(
            f"{schema_path}: required properties must match the documented ledger column order; "
            f"schema declares {list(columns)}"
        )
    if set(properties) != set(columns):
        raise ContractError(
            f"{schema_path}: properties and required must describe exactly the same fields"
        )

    non_blank: set[str] = set()
    patterns: list[tuple[str, re.Pattern[str]]] = []
    enums: list[tuple[str, frozenset[str]]] = []
    for name in columns:
        spec = properties[name]
        if not isinstance(spec, dict) or spec.get("type") != "string":
            raise ContractError(f"{schema_path}: property {name!r} must be a string type")
        if int(spec.get("minLength", 0)) >= 1:
            non_blank.add(name)
        pattern = spec.get("pattern")
        if pattern is not None:
            try:
                patterns.append((name, re.compile(pattern)))
            except re.error as exc:
                raise ContractError(f"{schema_path}: {name} pattern is invalid: {exc}") from exc
        allowed = spec.get("enum")
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed:
                raise ContractError(f"{schema_path}: {name} enum must be a non-empty list")
            enums.append((name, frozenset(allowed)))

    status_enum = dict(enums).get("status")
    if status_enum is None or ACTIVE_STATUS not in status_enum:
        raise ContractError(f"{schema_path}: status must enumerate {ACTIVE_STATUS!r}")
    unknown_sort = set(LEDGER_SORT_COLUMNS) - set(columns)
    if unknown_sort:
        raise ContractError(
            f"{schema_path}: sort columns not in the ledger: {sorted(unknown_sort)}"
        )

    return DecisionContract(
        columns=columns,
        non_blank_columns=frozenset(non_blank),
        patterns=tuple(patterns),
        enums=tuple(enums),
    )


def validate_decision_ledger(path: Path, contract: DecisionContract) -> LedgerSummary:
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ContractError(f"cannot read decision ledger {path}: {exc}") from exc

    # Read with standard csv quoting, but require that nothing was actually quoted. The ledger's
    # value proposition is that `cut -f5`, `awk -F'\t'`, a spreadsheet import and
    # `pandas.read_csv(sep='\t')` all agree; a single escaped field would break the naive tools
    # silently. The migration converts curator double quotes to typographic pairs precisely so this
    # holds, and this check is what keeps it holding.
    with handle:
        text = path.read_text(encoding="utf-8")
        if '"' in text:
            raise ContractError(
                f"{path} contains a double quote, so some field is escaped and naive "
                f"tab-splitting is no longer safe; use typographic quotes in ledger text"
            )
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        if tuple(reader.fieldnames or ()) != contract.columns:
            raise ContractError(
                "decision ledger columns must exactly match the documented contract"
            )

        seen_ids: set[str] = set()
        seen_active_assertions: set[tuple[str, str]] = set()
        previous_sort_key: tuple[str, ...] | None = None
        rows = 0
        active_rows = 0

        for line_number, row in enumerate(reader, start=2):
            rows += 1
            if None in row:
                raise ContractError(f"line {line_number}: more fields than the header declares")
            if any(value is None for value in row.values()):
                raise ContractError(f"line {line_number}: fewer fields than the header declares")

            for column, pattern in contract.patterns:
                if not pattern.fullmatch(row[column]):
                    raise ContractError(
                        f"line {line_number}: {column} {row[column]!r} does not match "
                        f"{pattern.pattern}"
                    )
            for column, allowed in contract.enums:
                if row[column] not in allowed:
                    raise ContractError(f"line {line_number}: invalid {column} {row[column]!r}")
            for column in sorted(contract.non_blank_columns):
                if not row[column].strip():
                    raise ContractError(f"line {line_number}: {column} must not be blank")

            decision_id = row["decision_id"]
            if decision_id in seen_ids:
                raise ContractError(f"line {line_number}: duplicate decision_id {decision_id}")
            seen_ids.add(decision_id)

            sort_key = tuple(row[column] for column in LEDGER_SORT_COLUMNS)
            if previous_sort_key is not None and sort_key < previous_sort_key:
                raise ContractError(
                    f"line {line_number}: ledger is not in deterministic sort order"
                )
            previous_sort_key = sort_key

            if row["status"] == ACTIVE_STATUS:
                active_rows += 1
                assertion_key = (row["subject_key"], row["field_name"])
                if assertion_key in seen_active_assertions:
                    raise ContractError(
                        "line "
                        f"{line_number}: duplicate active assertion for {assertion_key!r}"
                    )
                seen_active_assertions.add(assertion_key)

    return LedgerSummary(rows=rows, active_rows=active_rows)


def validate_parity_spec(path: Path) -> dict[str, Any]:
    spec = load_json(path)
    require_exact_keys(spec, PARITY_TOP_LEVEL_KEYS, f"{path}")
    if spec["contract_version"] != 1:
        raise ContractError("parity contract_version must be 1")
    if spec["baseline_release"] != BASELINE_RELEASE:
        raise ContractError(f"parity baseline_release must be {BASELINE_RELEASE}")
    for key in ("public_release_commit", "source_release_commit"):
        if not COMMIT_RE.fullmatch(str(spec[key])):
            raise ContractError(f"parity {key} must be a full 40-character commit SHA")

    if spec["expected_counts"] != EXPECTED_BASELINE_COUNTS:
        raise ContractError(
            f"parity counts differ from the frozen baseline: {spec['expected_counts']!r}"
        )

    raw = spec["raw_input"]
    if not isinstance(raw, dict):
        raise ContractError("parity raw_input must be an object")
    require_exact_keys(raw, PARITY_RAW_INPUT_KEYS, f"{path} raw_input")
    for key in ("archive_sha256", "uncompressed_sha256"):
        if not SHA256_RE.fullmatch(str(raw[key])):
            raise ContractError(f"parity raw_input.{key} must be a lowercase SHA-256")
    if raw["record_count"] != EXPECTED_BASELINE_COUNTS["source_records"]:
        raise ContractError("parity raw record_count does not match source_records")

    artifacts = spec["expected_artifacts"]
    if not isinstance(artifacts, list) or not artifacts:
        raise ContractError("parity expected_artifacts must be a non-empty list")
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise ContractError("each parity artifact must be an object")
        require_exact_keys(artifact, PARITY_ARTIFACT_KEYS, f"{path} expected_artifacts entry")
        artifact_path = artifact["path"]
        if not isinstance(artifact_path, str) or not artifact_path.startswith(RELEASE_PATH_PREFIX):
            raise ContractError(f"invalid parity artifact path: {artifact_path!r}")
        if artifact_path in seen_paths:
            raise ContractError(f"duplicate parity artifact path: {artifact_path}")
        seen_paths.add(artifact_path)
        if artifact["hash_scope"] not in HASH_SCOPES:
            raise ContractError(f"invalid hash_scope for {artifact_path}")
        if not SHA256_RE.fullmatch(str(artifact["sha256"])):
            raise ContractError(f"invalid SHA-256 for {artifact_path}")

    policy = spec["policy"]
    if not isinstance(policy, dict):
        raise ContractError("parity policy must be an object")
    require_exact_keys(policy, PARITY_POLICY_KEYS, f"{path} policy")
    if policy["existing_final_is_pipeline_input"] is not False:
        raise ContractError("existing final/ must never be a pipeline input")
    if policy["baseline_release_mutable"] is not False:
        raise ContractError(f"the {BASELINE_RELEASE} baseline must be immutable")
    return spec


def verify_raw_input(repository_root: Path, raw: dict[str, Any]) -> None:
    archive = repository_root / raw["path"]
    if not archive.is_file():
        raise ContractError(f"declared raw archive is missing: {raw['path']}")
    actual_archive = sha256_file(archive)
    if actual_archive != raw["archive_sha256"]:
        raise ContractError(
            f"{raw['path']} sha256 {actual_archive} does not match the parity contract "
            f"{raw['archive_sha256']}"
        )

    member = raw["archive_member"]
    try:
        with zipfile.ZipFile(archive) as handle:
            try:
                info = handle.getinfo(member)
            except KeyError as exc:
                raise ContractError(
                    f"{raw['path']} does not contain the declared member {member!r}"
                ) from exc
            if info.file_size != raw["uncompressed_bytes"]:
                raise ContractError(
                    f"{member} is {info.file_size} bytes, contract declares "
                    f"{raw['uncompressed_bytes']}"
                )
            digest = hashlib.sha256()
            with handle.open(info) as stream:
                for chunk in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(chunk)
    except (OSError, zipfile.BadZipFile) as exc:
        raise ContractError(f"cannot authenticate {raw['path']}: {exc}") from exc
    if digest.hexdigest() != raw["uncompressed_sha256"]:
        raise ContractError(
            f"{member} sha256 {digest.hexdigest()} does not match the parity contract "
            f"{raw['uncompressed_sha256']}"
        )


def validate_contract_shape(repository_root: Path) -> None:
    """Validate the schemas and the parity spec. Reads nothing under `final/`."""
    load_decision_contract(repository_root / DECISIONS_SCHEMA_PATH)
    validate_schema_document(
        repository_root / RULES_SCHEMA_PATH,
        required_title="Deterministic curation rule",
    )
    validate_parity_spec(repository_root / PARITY_SPEC_PATH)
