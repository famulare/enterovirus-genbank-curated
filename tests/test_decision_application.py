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
    # 2026-08-17, from the twenty decisions e506147 and 4b2fb32 added and the four whose status
    # they changed (two to `superseded`, two to `retired`). The two that retired and the two that
    # superseded leave `applied_unchanged`, which is why that falls while the two `not_in_force`
    # counts rise by two apiece; the new decisions land as 13 `applied_changed` and 4
    # `applied_filled_unresolved`.
    # +115 on 2026-07-31: the 95-record cVDPV epidemiological override and 20 strain-identity/
    # provenance decisions, every one filling a cell the rule had been declining.
    # +28 the same day: the reference_or_lab_text (24) and group_A_text_owned (4) decisions closing
    # the largest remaining `poliovirus_classification` discrepancy block, every one of those also
    # filling a cell the rule had been declining for want of usable sequence.
    # −492 the same day, when the reference-title text fallback landed: the counterfactual (ledger
    # withheld) used to be blank for every one of these 492 `poliovirus_classification` decisions —
    # the rule had nothing to say without the decision — and now the fallback gives it something to
    # say instead. 491 move to `applied_changed` (the fallback's text guess differs from what the
    # curator decided) and 1 to `applied_unchanged` (the guess happens to agree). Neither reverses a
    # decision: the ledger still wins for the real column value, exactly as before. This is the
    # counterfactual doing its job — revealing that curator judgment on these 492 records was doing
    # real work a plausible-but-cruder text read would not have replicated.
    # +2,770 on 2026-08-01: the upstream partition projection (1,379 rows) and the six short patent
    # deposits fill `is_poliovirus` for every record the build still declined a partition for, and
    # each one cascades — `virus_group` and `curation_status` directly, then `sample_origin`,
    # `surveillance_stream` and `poliovirus_classification` wherever the newly-scoped record has its
    # own evidence to read. 1,385 decisions filling 2,770 previously-declined cells is the shape of
    # a partition being the gate on four other columns.
    # +13 on 2026-08-01, release 4.1.0's whole content: the accession-level classification
    # adjudications. All 13 land here rather than in `applied_changed` because the counterfactual
    # withholds the *whole* ledger, which takes the partition with it — so without any decisions the
    # rule declines these records entirely rather than reaching the `wild` the real build shows them
    # moving off. `final/audit/decision_applications.tsv.gz` carries the per-decision proof, and
    # `tests/test_decision_ledger.py` asserts the shipped column against all 13. Net +11, because
    # the two `wild` rows the engineered/lab calls supersede were themselves counted here.
    # --- restated 2026-08-12, when the counterfactual stopped withholding more than the ledger ---
    #
    # Every arithmetic term above describes a measurement taken against a broken counterfactual.
    # `curate/apply.py:project_without_decisions` rebuilt each `RecordView` by naming five of its
    # nine fields, so it silently dropped `byte_identical`, `evidence`, `reference_titles` and
    # `membership_evidence` as well as the ledger. Rules that read those — `derive/engineered.py`,
    # `derive/classification.py`, `derive/partition.py` — therefore declined in the counterfactual
    # for want of *evidence*, and a decision that filled the resulting blank was recorded as
    # `applied_filled_unresolved` when the rule could in fact decide on its own.
    #
    # A second omission of the same shape, found by review and fixed with it: the counterfactual
    # also skipped `apply_isolate_linked_inference`. That pass is part of how the build reaches a
    # `poliovirus_classification`, so leaving it out claimed the rules could not resolve 21 cells
    # they do resolve. Running it moves 19 more to `applied_changed` and 2 to `applied_unchanged`.
    #
    # Withholding only the ledger moves 1,630 decisions out of `applied_filled_unresolved`: 1,131 to
    # `applied_changed` (the rule reaches a different answer, so the curator's judgment is doing
    # real work) and 499 to `applied_unchanged` (the rule now reaches the *same* answer, so the
    # decision is redundant with the rules as they stand). The totals are unchanged at 5,619
    # applications; what moved is the attribution, which was the one thing this table exists to
    # state. `applied_unchanged` going 25 -> 524 is the counterfactual finally doing the job
    # `build.py` describes it as doing — surfacing curation a rule has made redundant. It went to
    # 526 the same week, for the same reason and by a different route; see the note below.
    #
    # These three are flat numbers rather than sums because there is no honest decomposition: the
    # history above was measured against the wrong comparison, and re-deriving per-episode terms
    # from it would be inventing provenance. The commentary is kept as the record of what the
    # broken counterfactual reported.
    # 2026-08-12, R-DATE-2's identifier branch: two cells move `applied_changed` ->
    # `applied_unchanged`, both `AY308802`. Its `collection_year_curated = 1953` decision is now
    # redundant — withhold it and `country_year_optional_case` reads the same 1953 out of the
    # strain token `USA53`. The upstream stage had noticed the same coincidence and drawn the
    # opposite conclusion from it: because the inferred year agreed, an override-shadowing bug
    # there stayed invisible for weeks. Here it is the counterfactual reporting exactly what it
    # exists to report, and `AY308802` joins the Phase H population.
    #
    # The same day, R-TYPE-2's definition-line reading moves one more: `KC787121`'s
    # `corrected_type = Coxsackievirus A13` is now derivable, because the record's own title states
    # `CV-A13`. `applied_filled_unresolved` -> `applied_unchanged`, since the rule went from
    # declining the cell to reaching the curator's own answer.
    # And two more the same day, both `surveillance_stream`: `KP004243` and `KP004244` assert
    # `environmental`, and the `/environmental_sample` flag on each now reaches it unaided. Their
    # `/isolation_source` is empty, so nothing contradicts the flag.
    # 2026-08-13, R-ORIGIN-2's GenBank division branch: 53 `origin_class` decisions leave
    # `applied_filled_unresolved`, because the rule now has an answer of its own on a patent or
    # environmental deposit where it used to decline. 48 become `applied_changed` and 5
    # `applied_unchanged`.
    #
    # The 48 are the interesting ones and they vindicate the branch rather than contradicting it: 31
    # assert `human` and 17 `vaccine` on patent deposits the rule now calls `non-human`. A curator
    # read those particular patents and found a vaccine strain or human-derived material in them;
    # the rule reads only the division. The ledger wins, as it must, and the counterfactual now
    # states plainly that the curator's judgement is doing work — which is the whole point of
    # measuring against one.
    # +173 on 2026-08-14: every row of the `origin_unknown` projection fills a cell the rules
    # decline. Including `S61236`'s two, whose *real* values are determined rather than declined:
    # the counterfactual withholds the whole ledger and takes its `is_poliovirus = FALSE` with it,
    # so without any decisions the partition declines and the epi rules decline behind it.
    # -11 on 2026-08-14: the rule-redundant `serotype` retirements. They leave `applied_unchanged`
    # for `not_in_force_retired` and move no canonical cell, which is what `applied_unchanged` meant
    # in the first place — verified by rebuilding and diffing the table: 0 rows changed.
    # 2026-08-14, release 5.0.0's correctness pass. The three carve exclusions take their subjects
    # out of the carve, so the `classification` and `sampling_frame` decisions already on those
    # records become `subject_outside_carve` (6 -> 12) and their own new rows land as
    # `applied_exclusion` (173 -> 176). The five serotype relabels and six engineered TRUEs are
    # `applied_changed`, since the rules reach a different answer on every one.
    # +10 on 2026-11-17, release 5.1.0: the defective-interfering `classification` decisions. They
    # land here and not in `applied_changed` because `R-CLASS-2` declines these cells with or
    # without the ledger — 60 nt carries no VP1 window to measure — so the decision is the only
    # reason the cell has a value, which is exactly what this bucket means.
    "applied_filled_unresolved": 3559 - 3 + 4 + 10,
    # -4 more on 2026-08-15: four `iVDPV` decisions the attestation branch now reaches unaided,
    # because the record's own `/isolation_source` names an immunodeficient host and the rule reads
    # it. `iVDPV` in this tally goes 40 -> 44. They stay active under the 2026-08-14 ruling — the
    # branch that makes them redundant is a day old.
    # +1 on 2026-08-16: `DQ205099`'s `engineered_or_construct = TRUE`, the seventh record of the
    # class R-CONSTRUCT-2's two structural tests cannot reach. It changes the cell, so it lands
    # here rather than in `applied_unchanged`.
    "applied_changed": 1699 - 4 + 8 - 4 + 1 + 13,
    # +4 on 2026-08-14 from the named-wild-reference guard: four `classification` decisions
    # asserting `wild` on a Mahoney, Brunhilde, Lansing or Saukett deposit are now reached by the
    # rule unaided. They stay active under the 2026-08-14 ruling — R-CLASS-2 is the rule still
    # moving, and these four became redundant through a branch added this week.
    "applied_unchanged": 534 - 11 + 4 + 4 - 2,
    "applied_exclusion": 173 + 3,
    "not_in_force_retired": 183 + 11 + 2,
    "no_canonical_field": 123,
    "subject_outside_carve": 6 + 6,
    # +3 on 2026-07-31: the vocabulary repairs superseded the three active decisions whose value was
    # outside the controlled vocabulary (`CHAT`, a bare `engineered`, `iVPDV`).
    # +2 on 2026-08-01: `CS406483` and `PU749298`'s `wild` rows, superseded by the `engineered/lab`
    # the 4.1.0 adjudication asserts.
    "not_in_force_superseded": 10 + 3 + 2 + 2,
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
