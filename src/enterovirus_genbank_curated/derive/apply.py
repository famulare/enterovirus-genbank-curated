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
from enterovirus_genbank_curated.derive.outcome import NO_EVIDENCE, RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import BoundRule

NO_OVERRIDE = "FALSE"
OVERRIDE = "TRUE"
SOURCE_FEATURE_KEY = "source"
# The qualifiers that name a feature, and the ones whose text describes it. Both lists are the
# frozen upstream stage's own (`extract_genbank_metadata.feature_label` / `text_blob`), kept
# verbatim so `R-SCOPE-2` matches on the same string it was calibrated against. `region_name` occurs
# zero times in this corpus and `standard_name` once; they stay for fidelity and cost nothing.
LABEL_QUALIFIERS = ("gene", "product", "note", "region_name", "standard_name", "function")
TEXT_QUALIFIERS = ("product", "note", "gene", "region_name")


def build_record_views(
    tables: dict[str, list[dict[str, str]]],
    versions: Iterable[str],
    decisions: Mapping[str, Mapping[str, str]] | None = None,
    evidence: Mapping[str, Mapping[str, str]] | None = None,
    membership_evidence: Mapping[str, Mapping[str, str]] | None = None,
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

    # `record_id` is the version (`A01868.1`, not `A01868`) in this schema, the same identity
    # `references` rows carry, so no separate join table is needed to reach the reference titles for
    # a given version — one per `REFERENCE` block, concatenated, is the cited paper's own title.
    titles: dict[str, list[str]] = {}
    for row in tables["references"]:
        if row["record_id"] not in wanted:
            continue
        title = row.get("title", "")
        if title:
            titles.setdefault(row["record_id"], []).append(title)

    # Every feature, not just `source`, with the label the frozen upstream stage composed and the
    # span summed over its location parts so a joined feature counts once at its full length.
    # `R-SCOPE-2` is the only reader: genomic scope is a statement about a record's annotation, so
    # it needs the CDS and `mat_peptide` features the `qualifiers` map above deliberately omits.
    part_length: dict[str, int] = {}
    for row in tables["feature_location_parts"]:
        span = int(row["end_1based_inclusive"]) - int(row["start_1based"]) + 1
        part_length[row["feature_id"]] = part_length.get(row["feature_id"], 0) + span
    feature_qualifiers: dict[str, dict[str, list[str]]] = {}
    for row in tables["feature_qualifiers"]:
        record_id = feature_record[row["feature_id"]]
        if record_id not in wanted:
            continue
        feature_qualifiers.setdefault(row["feature_id"], {}).setdefault(
            row["qualifier_name"], []
        ).append(row["qualifier_value"])
    features: dict[str, list[dict[str, str]]] = {}
    for row in tables["features"]:
        record_id = row["record_id"]
        if record_id not in wanted:
            continue
        held = feature_qualifiers.get(row["feature_id"], {})
        label = " ".join(
            [row["feature_key"], *(v for key in LABEL_QUALIFIERS for v in held.get(key, ()))]
        )
        features.setdefault(record_id, []).append(
            {
                "key": row["feature_key"],
                "label": label,
                "length": str(part_length.get(row["feature_id"], 0)),
                "text": " ".join(v for key in TEXT_QUALIFIERS for v in held.get(key, ())),
            }
        )

    ledger = decisions or {}
    measured = evidence or {}
    membership_measured = membership_evidence or {}
    return [
        RecordView(
            version=record["version"],
            accession=record["accession"],
            record=record,
            qualifiers=qualifiers.get(record["version"], {}),
            decisions=ledger.get(record["accession"], {}),
            byte_identical=tuple(by_digest[record["sequence_sha256"]]),
            evidence=measured.get(record["version"], NO_EVIDENCE),
            reference_titles=" | ".join(titles.get(record["version"], ())),
            membership_evidence=membership_measured.get(record["version"], NO_EVIDENCE),
            features=tuple(features.get(record["version"], ())),
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
            # A declined outcome carries no basis by construction (`RuleOutcome.__post_init__`), so
            # there is nothing to check against the declared set. Exempting the declined case says
            # that; adding `""` to all twelve `evidence_bases` tuples instead would leave the check
            # unable to catch a resolving branch that genuinely forgot its basis.
            if outcome.resolved and outcome.evidence_basis not in implementation.declared_bases:
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
