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

# Measured, and pinned so a decision cannot quietly stop being applied.
#
# `applied_unchanged` is **zero on purpose**, and the story of that number is the argument for the
# status existing. It read 55, then 138 once R-ORIGIN-2 began reading `/host` outside poliovirus,
# then 162 once R-SURVEILLANCE-2 landed — each rule that grew made more curation redundant. On
# 2026-07-30 the curator retired all 162, which is why `not_in_force_retired` is 179 rather than 17.
# The retirement moved no canonical value: `applied_unchanged` had already established the rules
# reached those values alone, and the `final_value` witness digests in `oracle/parity.py` were
# unchanged across it. It did move `manual_override` on 162 rows, which is the honest consequence —
# the release says a human touched those cells and the rewrite no longer claims one did.
#
# A non-zero value here means new redundant curation has appeared and is worth a look.
# Re-pinned 2026-07-31, when R-CONSTRUCT-2 made `engineered_or_construct` a projected column. The
# 27 `engineered_or_construct` decisions stop being `field_not_projected` (2,209 -> 2,182) and land
# where they actually fall: 11 more `applied_changed`, and 13 `applied_unchanged` — a new status in
# this tally, and the interesting one. `applied_unchanged` means the structured rule reaches the
# same value the decision asserts, so those 13 rows are curation the rule made redundant, exactly as
# the counterfactual projection exists to reveal. They are left in the ledger rather than retired:
# a rule agreeing with a curator today is not a reason to discard the curator's evidence.
#
# `not_in_force_retired` 179 -> 183 and `not_in_force_superseded` 9 -> 10 are the re-adjudication's
# own remediation — four TRUE assertions withdrawn, one FALSE reversed.
# Re-pinned when R-CLASS-2 landed, and `field_not_projected` is **0** for the first time. That is
# the whole exercise in one number: every ledger field this repo maps to a canonical column now
# reaches a rule that projects it, so no decision is left asserting into a column nothing computes.
# The 2,209 that used to sit there are mostly `applied_filled_unresolved` now (458 -> 2,627): a
# curated classification or serotype on a record whose sequence or organism name does not settle it,
# which is the queue-and-ledger loop closing in the direction it was built for.
#
# `field_not_projected` is deliberately absent rather than pinned at zero.
# `assert_every_decision_is_accounted_for` tallies only statuses that occur, and a key pinned to 0
# would silently pass if the status stopped being computed at all.
# Re-pinned when the membership rescue closed the carve gap, and the movement is the best evidence
# yet that the carve was wrong rather than merely incomplete. `subject_outside_carve` falls 18 -> 6:
# twelve decisions were being recorded as asserting about a record the build did not carve, and all
# twelve are on records the rescue now admits. A curator had already stated an `origin_class`, a
# `sampling_frame` or a classification for them; the ledger knew they were poliovirus deposits while
# the carve did not. Those twelve land as 11 `applied_filled_unresolved` and 1 `applied_changed`.
#
# The remaining +2 on `applied_filled_unresolved` is the CAVA pair, `LY501105`/`LZ216100`.
# R-CONSTRUCT-2 declined on both until 2026-07-31, so their new FALSE rows fill a cell that was
# unresolved — the queue-and-ledger loop closing on the two records that were the queue's point.
EXPECTED_TALLY = {
    "applied_filled_unresolved": 2640,
    "applied_exclusion": 173,
    "not_in_force_retired": 183,
    "no_canonical_field": 123,
    "applied_changed": 31,
    "applied_unchanged": 24,
    "subject_outside_carve": 6,
    "not_in_force_superseded": 10,
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
