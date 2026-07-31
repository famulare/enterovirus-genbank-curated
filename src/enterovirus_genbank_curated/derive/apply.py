"""Run a bound rule over the corpus and turn its outcomes into provenance rows.

The `evidence_basis` check here is the one that makes the declared bases in `rule_implementation`
worth declaring: a rule returning a branch label it never published fails the build rather than
writing an undeclared value into a controlled-vocabulary column.

`manual_override` is `FALSE` on every row this emits. That is currently true rather than a
placeholder — no active ledger decision names `locality` — and it becomes a real computation in the
increment that applies decisions, which is also where `decision_id` joins on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import BoundRule

NO_OVERRIDE = "FALSE"
OVERRIDE = "TRUE"
SOURCE_FEATURE_KEY = "source"


def build_record_views(
    tables: dict[str, list[dict[str, str]]],
    versions: Iterable[str],
    decisions: Mapping[str, Mapping[str, str]] | None = None,
) -> list[RecordView]:
    """One view per requested version, in the corpus order the parser emitted.

    Restricting to `versions` rather than viewing the whole corpus keeps the carve decision in one
    place: `derive/metadata.py` decides who is in, and everything downstream projects only those.
    """
    wanted = set(versions)
    source_features = {
        row["feature_id"]
        for row in tables["features"]
        if row["feature_key"] == SOURCE_FEATURE_KEY
    }
    feature_record = {row["feature_id"]: row["record_id"] for row in tables["features"]}
    qualifiers: dict[str, dict[str, str]] = {}
    for row in tables["feature_qualifiers"]:
        feature_id = row["feature_id"]
        if feature_id not in source_features:
            continue
        record_id = feature_record[feature_id]
        if record_id not in wanted:
            continue
        qualifiers.setdefault(record_id, {}).setdefault(
            row["qualifier_name"], row["qualifier_value"]
        )

    # Grouped over the *whole* corpus rather than the carve, because "these are the same bytes" is a
    # fact about the sequence and does not stop being true when one of the twins is carved out.
    by_digest: dict[str, list[dict[str, str]]] = {}
    for record in tables["records"]:
        by_digest.setdefault(record["sequence_sha256"], []).append(record)

    ledger = decisions or {}
    return [
        RecordView(
            version=record["version"],
            accession=record["accession"],
            record=record,
            qualifiers=qualifiers.get(record["version"], {}),
            decisions=ledger.get(record["accession"], {}),
            byte_identical=tuple(by_digest[record["sequence_sha256"]]),
        )
        for record in tables["records"]
        if record["version"] in wanted
    ]


def project_field(bound: BoundRule, views: Sequence[RecordView]) -> list[dict[str, str]]:
    """Apply one bound rule to every view, returning provenance rows in view order."""
    if bound.implementation is None:
        raise ContractError(
            f"{bound.spec.rule_id} has no implementation ({bound.pending_reason}); it cannot "
            f"project"
        )
    implementation = bound.implementation
    parameters = dict(bound.spec.parameters)

    rows: list[dict[str, str]] = []
    for view in views:
        produced = implementation.fn(parameters, view)
        # A rule covering several canonical columns returns a mapping. R-DATE-RANGE covers two, and
        # requiring the keys to equal the declared set is what stops a rule writing an undeclared
        # column — the same reason `evidence_basis` is checked against `declared_bases` below.
        if implementation.fields:
            if not isinstance(produced, Mapping):
                raise ContractError(
                    f"{bound.spec.rule_id} declares {list(implementation.fields)} but returned "
                    f"{type(produced).__name__}, not a mapping of field to RuleOutcome"
                )
            if set(produced) != set(implementation.fields):
                raise ContractError(
                    f"{bound.spec.rule_id} returned fields {sorted(produced)}, not the declared "
                    f"{sorted(implementation.fields)}"
                )
            emitted = [(field, produced[field]) for field in implementation.fields]
        else:
            emitted = [(bound.spec.field_name, produced)]

        for canonical_field, outcome in emitted:
            if not isinstance(outcome, RuleOutcome):
                raise ContractError(
                    f"{bound.spec.rule_id} returned {type(outcome).__name__}, not a RuleOutcome"
                )
            if outcome.evidence_basis not in implementation.declared_bases:
                raise ContractError(
                    f"{bound.spec.rule_id} emitted evidence_basis {outcome.evidence_basis!r}, "
                    f"which it does not declare; declared: "
                    f"{sorted(implementation.declared_bases)}"
                )
            rows.append(
                {
                    "accession": view.accession,
                    "version": view.version,
                    "canonical_field": canonical_field,
                    "final_value": outcome.value,
                    "source_field": outcome.source_field,
                    "source_value": outcome.source_value,
                    "winning_rule_id": bound.spec.rule_id,
                    "evidence_basis": outcome.evidence_basis,
                    "manual_override": OVERRIDE if outcome.manual_override else NO_OVERRIDE,
                    "unresolved_reason": outcome.unresolved_reason,
                }
            )
    return rows
