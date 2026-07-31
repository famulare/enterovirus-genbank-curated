"""Every curation decision has a stated outcome, and silence is a build failure.

D2 is the reason this exists: an assertion sat in the ledger for two releases while the pipeline
recomputed the value from scratch, and nothing said the assertion had no effect. These tests pin the
statuses and both set-equality directions, and each one names the failure it prevents.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.build import build_metadata_layer
from enterovirus_genbank_curated.contracts import DECISION_COLUMNS, ContractError
from enterovirus_genbank_curated.curate.apply import (
    APPLICATION_STATUSES,
    APPLIED_CHANGED,
    APPLIED_EXCLUSION,
    APPLIED_FILLED_UNRESOLVED,
    APPLIED_UNCHANGED,
    NO_CANONICAL_FIELD,
    NOT_IN_FORCE_RETIRED,
    REGISTRY_FIELD_TO_CANONICAL,
    DecisionApplication,
    apply_decisions,
    assert_every_decision_is_accounted_for,
)

# Measured, and pinned so a decision cannot quietly stop being applied. `applied_unchanged` is the
# interesting one: 138 assertions the rules now reach on their own, so they are candidates for
# retirement rather than curation doing work. It rose from 55 and `applied_filled_unresolved` fell
# from 221 by the same 83 when R-ORIGIN-2 began reading `/host` outside poliovirus — decisions that
# had been the only source of a value became redundant with the rule. That movement is the status
# earning its place: no other column would have shown it.
EXPECTED_TALLY = {
    "field_not_projected": 2553,
    "applied_filled_unresolved": 138,
    "applied_exclusion": 173,
    "no_canonical_field": 123,
    "applied_unchanged": 138,
    "subject_outside_carve": 18,
    "applied_changed": 17,
    "not_in_force_retired": 17,
    "not_in_force_superseded": 9,
}


def decision(**overrides: str) -> dict[str, str]:
    row = dict.fromkeys(DECISION_COLUMNS, "")
    row.update(
        decision_id="D-000000000001",
        accession="AF000001",
        subject_key="AF000001",
        field_name="origin_class",
        new_value="human",
        status="active",
    )
    row.update(overrides)
    return row


def provenance_row(field: str, value: str, version: str = "AF000001.1") -> dict[str, str]:
    return {"version": version, "canonical_field": field, "final_value": value}


CORPUS = frozenset({"AF000001"})
CARVED = {"AF000001": "AF000001.1"}


def test_a_decision_the_rule_would_have_reached_anyway_is_named_as_such() -> None:
    """`applied_unchanged` is not a nicety: it identifies curation a rule has made redundant."""
    (application,) = apply_decisions(
        [decision()],
        [provenance_row("sample_origin", "human")],
        {("AF000001.1", "sample_origin"): {"final_value": "human", "unresolved_reason": ""}},
        CORPUS,
        CARVED,
    )
    assert application.application_status == APPLIED_UNCHANGED
    assert application.value_without_decision == "human"


def test_a_decision_that_moves_the_value_is_distinguished_from_one_that_does_not() -> None:
    (application,) = apply_decisions(
        [decision()],
        [provenance_row("sample_origin", "human")],
        {("AF000001.1", "sample_origin"): {"final_value": "non-human", "unresolved_reason": ""}},
        CORPUS,
        CARVED,
    )
    assert application.application_status == APPLIED_CHANGED
    assert application.value_without_decision == "non-human"


def test_a_decision_filling_a_declined_cell_is_named_separately() -> None:
    """Distinct from `applied_changed`: the decision is the only reason the cell has any value."""
    (application,) = apply_decisions(
        [decision()],
        [provenance_row("sample_origin", "human")],
        {("AF000001.1", "sample_origin"): {"final_value": "", "unresolved_reason": "no_evidence"}},
        CORPUS,
        CARVED,
    )
    assert application.application_status == APPLIED_FILLED_UNRESOLVED


def test_a_withdrawn_decision_is_recorded_as_not_in_force() -> None:
    (application,) = apply_decisions(
        [decision(status="retired")], [], {}, CORPUS, CARVED
    )
    assert application.application_status == NOT_IN_FORCE_RETIRED


def test_an_assertion_with_no_canonical_column_says_so_rather_than_looking_ignored() -> None:
    (application,) = apply_decisions(
        [decision(field_name="reference_label", new_value="Sabin 1")], [], {}, CORPUS, CARVED
    )
    assert application.application_status == NO_CANONICAL_FIELD
    assert application.canonical_field == ""


def test_an_exclusion_is_verified_to_have_excluded() -> None:
    """173 decisions whose entire effect is an absence. Trusting the absence is not checking it."""
    (application,) = apply_decisions(
        [decision(field_name="membership_excluded", new_value="TRUE")],
        [],
        {},
        CORPUS,
        {},  # not in the carve, which is what the decision asserts
    )
    assert application.application_status == APPLIED_EXCLUSION

    with pytest.raises(ContractError, match="did not take effect"):
        apply_decisions(
            [decision(field_name="membership_excluded", new_value="TRUE")],
            [],
            {},
            CORPUS,
            CARVED,  # still carved, so the exclusion silently failed
        )


def test_an_unmapped_ledger_field_is_a_build_failure() -> None:
    """B27 is the absence of this map. A field missing from it must not default to "ignored"."""
    with pytest.raises(ContractError, match="REGISTRY_FIELD_TO_CANONICAL"):
        apply_decisions([decision(field_name="invented_field")], [], {}, CORPUS, CARVED)


def test_a_decision_naming_a_record_outside_the_corpus_is_a_build_failure() -> None:
    with pytest.raises(ContractError, match="not in the source corpus"):
        apply_decisions([decision(accession="ZZ999999")], [], {}, CORPUS, CARVED)


def test_an_unimplemented_field_is_named_rather_than_treated_as_missing() -> None:
    """`sample_origin` absent from the projection means no rule ran, not that a row went missing."""
    (application,) = apply_decisions(
        [decision()], [provenance_row("specimen_type", "stool")], {}, CORPUS, CARVED
    )
    assert application.application_status == "field_not_projected"


def test_a_carved_record_with_no_provenance_row_is_a_build_failure() -> None:
    """The ledger and the build disagreeing about what exists must not ship as a status.

    Distinct from the case above: here the field *is* projected — another record has a row for it —
    so this record lacking one means the build dropped it.
    """
    other_record = provenance_row("sample_origin", "human", version="AF000002.1")
    with pytest.raises(ContractError, match="no provenance row exists"):
        apply_decisions([decision()], [other_record], {}, CORPUS, CARVED)


def test_accounting_fails_in_both_directions() -> None:
    """A missing row is D2; an invented row means the build made curation up."""
    ledger = [decision()]
    with pytest.raises(ContractError, match="have no row"):
        assert_every_decision_is_accounted_for(ledger, [])
    invented = DecisionApplication(
        decision_id="D-nonexistent", accession="AF000001", registry_field="origin_class",
        canonical_field="sample_origin", asserted_value="human", value_without_decision="",
        final_value="human", application_status=APPLIED_UNCHANGED,
    )
    with pytest.raises(ContractError, match="name no decision"):
        assert_every_decision_is_accounted_for(ledger, [invented])


def test_every_mapped_target_is_a_canonical_column_or_the_inclusion_pseudo_field() -> None:
    """A target that is not a canonical column could never be compared to anything."""
    from enterovirus_genbank_curated.contracts import CANONICAL_COLUMNS
    from enterovirus_genbank_curated.curate.apply import CANONICAL_INCLUSION

    for registry_field, targets in REGISTRY_FIELD_TO_CANONICAL.items():
        for target in targets:
            assert target in CANONICAL_COLUMNS or target == CANONICAL_INCLUSION, (
                f"{registry_field} -> {target} is neither a canonical column nor the carve"
            )


@pytest.mark.slow
def test_the_real_ledger_is_fully_accounted_for(repository_root: Path, tmp_path: Path) -> None:
    result = build_metadata_layer(repository_root, tmp_path)
    assert result.application_tally == EXPECTED_TALLY
    assert set(result.application_tally) <= APPLICATION_STATUSES
    # One row per decision per canonical field it reaches, so at least one per ledger row.
    assert len(result.applications) == sum(EXPECTED_TALLY.values())
