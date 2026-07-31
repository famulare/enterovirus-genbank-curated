"""What actually happened to every curation decision, recorded per decision rather than assumed.

This is the D2 lesson turned into an artifact. A decision was recorded in the ledger, the pipeline
recomputed the value from scratch on every build, and nobody noticed for two releases that the
assertion had no effect — because nothing anywhere said what became of it. `registry/README.md`
commits to fixing that with a `decision_applications` table; this is it.

## Every outcome is named, and silence is not one of them

The statuses below are exhaustive over the ledger. A decision that reaches no row at all is not
"absent from the table" — it is a build failure, because that is precisely the state D2 was in.

* `applied_changed` — in force, and the value differs from what the rule alone would have produced.
* `applied_unchanged` — in force, and the rule would have reached the same value anyway. Worth
  distinguishing: it means the curation is now *redundant* with a rule, which is a candidate for
  retirement rather than a decision doing work.
* `applied_filled_unresolved` — in force, and the rule would have declined. The decision is the only
  reason the cell has a value.
* `not_in_force_retired` / `not_in_force_superseded` — the curator withdrew or replaced it.
  Honouring
  these would resurrect a decision that was taken back.
* `field_not_projected` — the field it asserts has no implemented rule yet, so there is nothing for
  it
  to act on. Distinct from being ignored: it names *why*.
* `subject_outside_carve` — the record is not in the canonical carve, so no canonical value exists.

## What is a build failure instead of a status

An active decision naming an accession that is not in the corpus at all, and an active decision on
an
implemented field whose carved record produced no provenance row. Both mean the ledger and the build
disagree about what exists, and giving either a status would let the disagreement ship.

## How `applied_changed` is distinguished from `applied_unchanged`

By projecting every field twice over the same records — once with the ledger and once with it
withheld — and comparing. That is the only honest way to say a decision *changed* something: it
needs
the counterfactual, and no amount of inspecting the final value supplies it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.apply import project_field
from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.registry.rules import BoundRule

APPLIED_CHANGED = "applied_changed"
APPLIED_UNCHANGED = "applied_unchanged"
APPLIED_FILLED_UNRESOLVED = "applied_filled_unresolved"
NOT_IN_FORCE_RETIRED = "not_in_force_retired"
NOT_IN_FORCE_SUPERSEDED = "not_in_force_superseded"
FIELD_NOT_PROJECTED = "field_not_projected"
SUBJECT_OUTSIDE_CARVE = "subject_outside_carve"
# Applied, but to the carve rather than to a cell: the record is absent because the ledger says so.
APPLIED_EXCLUSION = "applied_exclusion"
# The canonical schema has no column this assertion could reach. Distinct from a rule not yet
# written.
NO_CANONICAL_FIELD = "no_canonical_field"
CANONICAL_INCLUSION = "canonical_inclusion"

APPLICATION_STATUSES = frozenset(
    {
        APPLIED_CHANGED,
        APPLIED_UNCHANGED,
        APPLIED_FILLED_UNRESOLVED,
        NOT_IN_FORCE_RETIRED,
        NOT_IN_FORCE_SUPERSEDED,
        FIELD_NOT_PROJECTED,
        SUBJECT_OUTSIDE_CARVE,
        APPLIED_EXCLUSION,
        NO_CANONICAL_FIELD,
    }
)

NOT_IN_FORCE = {"retired": NOT_IN_FORCE_RETIRED, "superseded": NOT_IN_FORCE_SUPERSEDED}

# Ledger `field_name` -> the canonical fields it can reach. One ledger field may reach several: an
# `is_poliovirus` assertion decides the partition, and `curation_status` follows from it. Backlog
# B27
# is the absence of exactly this map.
REGISTRY_FIELD_TO_CANONICAL: dict[str, tuple[str, ...]] = {
    "is_poliovirus": ("virus_group", "curation_status"),
    "origin_class": ("sample_origin",),
    "specimen_type": ("specimen_type",),
    "collection_year_curated": ("collection_date", "collection_date_precision"),
    "sampling_frame": ("surveillance_stream",),
    "classification": ("poliovirus_classification",),
    "verified_classification": ("poliovirus_classification",),
    "serotype": ("virus_type",),
    "confirmed_serotype": ("virus_type",),
    "corrected_type": ("virus_type",),
    "engineered_or_construct": ("engineered_or_construct",),
    # These two do not set a canonical value; they remove the record from the carve. R-EXCLUDE-1's
    # own `field_name` is the honest target, and the check below verifies the exclusion actually
    # took
    # rather than assuming it — 173 decisions whose whole effect is an absence.
    "membership_excluded": (CANONICAL_INCLUSION,),
    "carve_excluded": (CANONICAL_INCLUSION,),
    # Curation the canonical schema has no column for. `canonical_reference` and `reference_label`
    # feed reference selection, `canonical_reference_available` a per-serotype availability flag,
    # and
    # `epi_context` is prose narrowing an already-projected field. Naming them as reaching nothing
    # is
    # the point: they are not unapplied, there is no canonical cell for them to reach.
    "canonical_reference": (),
    "canonical_reference_available": (),
    "reference_label": (),
    "epi_context": (),
}

APPLICATION_COLUMNS = (
    "decision_id",
    "accession",
    "registry_field",
    "canonical_field",
    "asserted_value",
    "value_without_decision",
    "final_value",
    "application_status",
)


@dataclass(frozen=True)
class DecisionApplication:
    decision_id: str
    accession: str
    registry_field: str
    canonical_field: str
    asserted_value: str
    value_without_decision: str
    final_value: str
    application_status: str

    def as_row(self) -> dict[str, str]:
        return {column: getattr(self, column) for column in APPLICATION_COLUMNS}


def project_without_decisions(
    bound: Sequence[BoundRule], views: Sequence[RecordView]
) -> dict[tuple[str, str], dict[str, str]]:
    """Every implemented field projected again with the ledger withheld, keyed by (version, field).

    The counterfactual. Without it, `applied_changed` and `applied_unchanged` are indistinguishable,
    and "this decision did something" becomes an assumption rather than a measurement.
    """
    stripped = [
        RecordView(
            version=view.version,
            accession=view.accession,
            record=view.record,
            qualifiers=view.qualifiers,
            decisions={},
        )
        for view in views
    ]
    return {
        (row["version"], row["canonical_field"]): row
        for rule in bound
        if rule.implementation is not None
        for row in project_field(rule, stripped)
    }


def apply_decisions(
    ledger: Sequence[Mapping[str, str]],
    provenance: Sequence[Mapping[str, str]],
    counterfactual: Mapping[tuple[str, str], Mapping[str, str]],
    corpus_accessions: frozenset[str],
    carved_versions: Mapping[str, str],
) -> list[DecisionApplication]:
    """One row per (decision, canonical field it can reach); at least one row per decision."""
    projected = {
        (row["version"], row["canonical_field"]): row for row in provenance
    }
    implemented = {field for _, field in projected}

    applications: list[DecisionApplication] = []
    for decision in ledger:
        decision_id = decision["decision_id"]
        accession = decision["accession"]
        registry_field = decision["field_name"]
        asserted = decision["new_value"]

        if registry_field not in REGISTRY_FIELD_TO_CANONICAL:
            raise ContractError(
                f"{decision_id}: ledger field {registry_field!r} is not in "
                f"REGISTRY_FIELD_TO_CANONICAL, so nothing states which canonical field it reaches "
                f"— which is the state backlog B27 describes"
            )
        status_override = NOT_IN_FORCE.get(decision["status"])
        targets = REGISTRY_FIELD_TO_CANONICAL[registry_field]

        if not targets:
            applications.append(
                DecisionApplication(
                    decision_id=decision_id, accession=accession, registry_field=registry_field,
                    canonical_field="", asserted_value=asserted, value_without_decision="",
                    final_value="",
                    application_status=status_override or NO_CANONICAL_FIELD,
                )
            )
            continue

        # Only a decision that targets a canonical field has to name a record. One row asserts a
        # per-serotype flag and carries no accession at all, which is legitimate rather than a
        # record the build failed to find.
        if accession not in corpus_accessions:
            raise ContractError(
                f"{decision_id}: accession {accession!r} targets {targets} but is not in the "
                f"source corpus, so the ledger and the build disagree about what exists"
            )
        version = carved_versions.get(accession, "")

        for canonical_field in targets:
            if status_override is not None:
                status, without, final = status_override, "", ""
            elif canonical_field == CANONICAL_INCLUSION:
                # The whole effect is an absence, so verify the absence rather than trusting it.
                if version:
                    raise ContractError(
                        f"{decision_id}: the ledger excludes {accession} but the carve "
                        f"contains it, so an active exclusion did not take effect"
                    )
                status, without, final = APPLIED_EXCLUSION, "in_carve", "excluded"
            elif not version:
                status, without, final = SUBJECT_OUTSIDE_CARVE, "", ""
            elif canonical_field not in implemented:
                status, without, final = FIELD_NOT_PROJECTED, "", ""
            else:
                row = projected.get((version, canonical_field))
                if row is None:
                    raise ContractError(
                        f"{decision_id}: {accession} is in the carve and {canonical_field} is "
                        f"projected, but no provenance row exists for it"
                    )
                before = counterfactual.get((version, canonical_field), {})
                without = before.get("final_value", "")
                final = row["final_value"]
                if before.get("unresolved_reason"):
                    status = APPLIED_FILLED_UNRESOLVED
                elif without != final:
                    status = APPLIED_CHANGED
                else:
                    status = APPLIED_UNCHANGED
            applications.append(
                DecisionApplication(
                    decision_id=decision_id,
                    accession=accession,
                    registry_field=registry_field,
                    canonical_field=canonical_field,
                    asserted_value=asserted,
                    value_without_decision=without,
                    final_value=final,
                    application_status=status,
                )
            )
    return applications


def assert_every_decision_is_accounted_for(
    ledger: Sequence[Mapping[str, str]], applications: Sequence[DecisionApplication]
) -> dict[str, int]:
    """Set equality both ways on `decision_id`, and every status from the declared vocabulary.

    The one-directional check is not enough. A decision missing from the table is D2; a row for a
    decision the ledger does not contain means the build invented curation.
    """
    ledger_ids = {row["decision_id"] for row in ledger}
    applied_ids = {application.decision_id for application in applications}
    missing = sorted(ledger_ids - applied_ids)
    invented = sorted(applied_ids - ledger_ids)
    if missing or invented:
        raise ContractError(
            f"decision applications do not account for the ledger exactly: {len(missing)} "
            f"decisions have no row ({missing[:5]}), {len(invented)} rows name no decision "
            f"({invented[:5]})"
        )
    undeclared = sorted(
        {a.application_status for a in applications} - APPLICATION_STATUSES
    )
    if undeclared:
        raise ContractError(f"undeclared application statuses: {undeclared}")

    tally: dict[str, int] = {}
    for application in applications:
        tally[application.application_status] = tally.get(application.application_status, 0) + 1
    return tally
