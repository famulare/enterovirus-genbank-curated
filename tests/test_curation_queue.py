"""The curation queue: what a rule's decline turns into.

The queue is the half of honest declining that makes it useful. Without it, `unresolved_reason` is a
note nobody acts on and the rewrite just ships a permanently emptier table than the release.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from enterovirus_genbank_curated.build import build_metadata_layer
from enterovirus_genbank_curated.curate.queue import (
    REGISTRY_FIELD_FOR_CANONICAL,
    RESOLUTION_DECISION,
    RESOLUTION_RULE_PARAMETER,
    build_queue,
    queue_id,
)
from enterovirus_genbank_curated.derive.epi import UNRESOLVED_NO_SOURCE
from enterovirus_genbank_curated.derive.partition import (
    UNRESOLVED_FOLLOWS_PARTITION,
    UNRESOLVED_UNINFORMATIVE,
)

# Summed across fields, so a record needing two decisions counts twice — a measure of work, not of
# records. `curation_status` declines on the same records as `virus_group` and is absent because it
# follows the partition rather than needing a decision of its own; sample_origin declines that are
# themselves consequences of an undecided partition are excluded for the same reason.
#
# 24,710 since 2026-07-31: R-CONSTRUCT-2 declines on `LY501105` and `LZ216100`, the one pair the
# `engineered_or_construct` re-adjudication left open in either direction. Those two are the only
# queue items in the whole build that exist because a *curator* withheld a decision rather than
# because a record is silent, and they are the shape the queue is for — a rule refusing to invent
# an answer the adjudication explicitly declined to give.
#
# 26,903 the same day, when R-TYPE-2 landed: 2,193 `virus_type` declines join, all but 37 of them a
# record whose organism name states no type. That is the largest single population in the queue that
# a *sequence* stage would clear rather than a curator — 685 `Enterovirus C` records alone — and it
# is listed as curation work because until that stage exists a human is what resolves it.
#
# 28,563 when the membership rescue closed the carve gap, and the +67 is three terms:
#   + 23 x 3  the rescued records join `specimen_type`, `virus_type` and `virus_group`, declining on
#             all three for the same reason they were rescued — a patent deposit with no
#             `/isolation_source` and an organism name that names nothing
#   −  2      `engineered_or_construct` leaves the queue entirely: its only two items were
#             `LY501105`/`LZ216100`, and the curator closed both on 2026-07-31
# `surveillance_stream`, `sample_origin` and `poliovirus_classification` do not move, because the
# rescued records decline on those *following the partition*, and partition-consequent declines are
# excluded from the queue by the rule above.
#
# 28,392 when a curated classification began entailing poliovirus membership, and the −171 is two
# terms pulling opposite ways:
#   − 259  `virus_group` stops declining on the records whose classification a curator has stated
#   +  88  `surveillance_stream` *gains* work. Those 259 records were declining stream under
#          `follows_unresolved_virus_group`, which the queue excludes as consequential; now that the
#          partition is decided, 88 of them decline under `no_surveillance_context_in_record`
#          instead, which is real work. The total stream declines do not move (8,650 either way) —
#          only the reason does, and the reason is what decides whether it is queued.
# `poliovirus_classification` does not move: it sheds 259 declines, but all 259 were
# partition-consequent and so were never queued in the first place.
#
# 28,244 when the capsid (P1) nucleotide fallback landed: 148 records that were declining
# `poliovirus_classification` for want of usable sequence now resolve, and that is the whole
# movement — every other field's declines are untouched by a rule that only ever *fills* a cell VP1
# could not reach.
# 28,241 when the vocabulary repairs landed 2026-07-31: 3 `poliovirus_classification` declines
# (`AJ416942`, `DQ205099`, `FJ517648`, whose active decisions asserted a value outside the
# controlled vocabulary) resolve and leave the queue. The 115 cVDPV/strain-identity decisions the
# same day do not move this count: every one of those already had a resolved value, just the wrong
# one, so none was ever queued.
#
# 28,213 when the reference_or_lab_text (24) and group_A_text_owned (4) decisions landed the same
# day: 28 more `poliovirus_classification` declines resolve and leave the queue, closing the
# largest remaining discrepancy block (`declined_too_little_sequence`).
#
# 28,153 the same day, when `MIN_VP1_NT`/`MIN_CAPSID_NT` dropped to 50 nt (matching MAD-VDPV's own
# `MIN_SEROTYPE_COMPARED_NT`) with a chunked-homogeneity guard extended to VP1 for the newly-opened
# sub-300 nt territory: 60 more `poliovirus_classification` declines resolve, every one agreeing
# with the shipped classification.
#
# 27,445 the same day, when the reference-title text fallback landed
# (`needs_other_data_text_fallback`): 708 more `poliovirus_classification` declines resolve — 705
# agreeing with the shipped classification and 3 (`AF083938`, `HM537010`, `MG212473`) not, a known,
# documented cost of asking a study title a record-level question (see `oracle/parity.py`). A
# decline leaving the queue does not require the value to be right, only that the cell is no longer
# silent.
#
# 27,254 the same day, when isolate-linked inference landed: 191 more `poliovirus_classification`
# declines resolve by inheriting a sibling accession's measured classification — 190 agreeing with
# the shipped value and 1 (`X70506`) not, the known `V01149.1` (Mahoney) trap reaching a second
# record (see `oracle/parity.py`). 27,199, 2026-08-01: the capsid-AA membership band resolves
# `virus_group` directly for 211 records (`-211`, real work leaving the queue). For the same 211,
# `sample_origin` and `surveillance_stream` stop declining *on the partition* and start declining,
# for the ones still short of their own evidence, on their own reason instead — 31 records with no
# `/host`/specimen text (`+31`) and 125 with no surveillance context in the record (`+125`), both
# newly real work rather than a decline excluded as partition-consequent.
# `poliovirus_classification` does not move: every one of the 211 fully resolves there (a value or a
# determined blank), so none of them was ever queued work to begin with. Net: 27,254 − 211 + 31 +
# 125 = 27,199.
EXPECTED_QUEUE_WORK_ITEMS = 28244 - 3 - 28 - 60 - 708 - 191 - 211 + 31 + 125
# 28,496 when R-CLASS-2 landed: 3,425 `poliovirus_classification` declines join, 1,832 of them
# records whose virus group is undecided and so already in the queue under `virus_group`. A record
# needing two decisions counts twice here on purpose — this is a measure of work, not of records.
# One group, not two: both declined records deposit `division=PAT`, and the queue groups by the
# input the rule examined, so the pair the curator left open arrives as one question. That is the
# grouping working — an answer to it is one adjudication covering both.
#
# 304 when the membership rescue landed: +6 −1. The 23 rescued records add **six** groups and not 23
# questions, because they carry only three distinct organism names and each name is a group under
# both `virus_group` and `virus_type` — `synthetic construct` (13 records), `unidentified` (8) and
# `Homo sapiens` (2). The −1 is `engineered_or_construct` leaving the queue with its single group.
#
# 67 new declined cells arriving as 6 questions is the grouping earning its keep, and the questions
# are the right ones: "is a `synthetic construct` patent deposit whose capsid is 2% from Sabin a
# poliovirus, and what type is it" is one adjudication, not thirteen.
#
# 302 when the entailment landed. Exactly two groups disappear, both under `virus_group`: the
# `Enterovirus C` (173 records) and `Enterovirus coxsackiepol` (82) questions empty out completely,
# because every record that was in them carries a curated classification. The `Homo sapiens` and
# `unidentified` groups survive — the entailment reaches 2 records in each and the membership rescue
# left others behind.
#
# Still 302 after the capsid fallback: the 148 newly-resolved records all shared the single
# `too_little_sequence_compared_to_measure_divergence`, no-source-value group under
# `poliovirus_classification`, which had 1,557 records in it before and has 1,409 now — one group
# shrinking, not a group disappearing or a new one appearing.
#
# 299 when the vocabulary repairs landed 2026-07-31: three one-record groups disappear under
# `poliovirus_classification`'s `curated_value_outside_the_controlled_vocabulary` reason, one per
# distinct malformed source_value (`CHAT`, `engineered`, `iVPDV`) — groups are keyed by the exact
# input the rule declined on, so three different malformed values were always three groups, not
# one. The 115 cVDPV/strain-identity decisions the same day touch no group: every one of those
# records already had a resolved value, so none was ever queued.
#
# Still 299 when the reference_or_lab_text (24) and group_A_text_owned (4) decisions landed the
# same day: all 28 shared the single `too_little_sequence_compared_to_measure_divergence`,
# no-source-value group under `poliovirus_classification` with the 1,381 records that remain
# declined for the same reason — one group shrinking, not a group disappearing.
#
# Still 299 when the VP1/capsid floor dropped to 50 nt the same day: the 60 newly-resolved records
# shared that same single group with the 1,321 that remain declined.
#
# Still 299 when the text fallback landed the same day: the 708 newly-resolved records shared that
# same single `too_little_sequence_compared_to_measure_divergence`, no-source-value group with the
# 613 that remain declined for the same reason.
#
# Still 299 when isolate-linked inference landed the same day: the 191 newly-resolved records shared
# that same single group with the 422 that remain declined for the same reason (no divergence
# measurement and no isolate link either).
# 302, 2026-08-01: the membership band's 211 newly-decided records shed their `virus_group` group
# entirely (every uninformative-organism-name group these records sat in also had other, still-
# undecided members) and mostly land in `sample_origin`/`surveillance_stream` groups that already
# existed for other records (no new group), except a handful of `surveillance_stream` group keys
# (e.g. `opv`, `human feces`) that no undecided-partition record had ever populated before — net +3.
EXPECTED_QUEUE_GROUPS = 302 - 3 + 3  # 299 (2026-07-31 baseline) + 3 (2026-08-01, above)


def declined(
    field: str, rule_id: str, reason: str, source_value: str, version: str
) -> dict[str, str]:
    return {
        "version": version,
        "canonical_field": field,
        "winning_rule_id": rule_id,
        "unresolved_reason": reason,
        "source_value": source_value,
    }


def test_records_declining_on_the_same_input_become_one_group() -> None:
    """The point of the queue: 462 records with the same isolation_source are one decision."""
    rows = [
        declined("specimen_type", "R-SPECIMEN-2", "no_specimen_keyword_in_isolation_source",
                 "conjunctival swab", f"AB{n:06d}.1")
        for n in range(5)
    ]
    (group,) = build_queue(rows)
    assert len(group.versions) == 5
    assert group.group_key == "conjunctival swab"
    # Examples are the first three by version, so a worksheet row is reproducible.
    assert group.as_row()["example_versions"] == "AB000000.1 AB000001.1 AB000002.1"
    assert group.as_row()["record_count"] == "5"


def test_a_resolved_row_produces_no_queue_work() -> None:
    resolved = {
        "version": "AB000001.1",
        "canonical_field": "locality",
        "winning_rule_id": "R-GEO-LOCALITY-2",
        "unresolved_reason": "",
        "source_value": "Sindh",
    }
    assert build_queue([resolved]) == []


def test_a_consequential_decline_is_not_queued_as_its_own_work() -> None:
    """`curation_status` declines only because `virus_group` did.

    Queueing both would ask the curator for the same decision twice under two field names, and a
    queue that overstates its own size is worse than no queue.
    """
    rows = [
        declined("virus_group", "R-PARTITION-1", UNRESOLVED_UNINFORMATIVE,
                 "Enterovirus C", "AB000001.1"),
        declined("curation_status", "R-STATUS-1", UNRESOLVED_FOLLOWS_PARTITION,
                 "Enterovirus C", "AB000001.1"),
    ]
    groups = build_queue(rows)
    assert [group.canonical_field for group in groups] == ["virus_group"]


def test_a_resolution_must_be_filed_under_the_ledger_field_not_the_canonical_column() -> None:
    """Filing against the canonical name validates, sits in the ledger, and changes nothing.

    That is the D2 failure, so the queue names the field a resolution has to use.
    """
    (group,) = build_queue(
        [declined("virus_group", "R-PARTITION-1", UNRESOLVED_UNINFORMATIVE, "Enterovirus C", "A.1")]
    )
    assert group.canonical_field == "virus_group"
    assert group.registry_field == "is_poliovirus"


def test_a_generalising_gap_asks_for_a_rule_change_and_a_one_off_asks_for_a_decision() -> None:
    """Boundary 3, made operational: a mapping is a rule, a subject is a decision."""
    (keyword,) = build_queue(
        [declined("specimen_type", "R-SPECIMEN-2", "no_specimen_keyword_in_isolation_source",
                  "conjunctival swab", "A.1")]
    )
    assert keyword.suggested_resolution_kind == RESOLUTION_RULE_PARAMETER

    (membership,) = build_queue(
        [declined("virus_group", "R-PARTITION-1", UNRESOLVED_UNINFORMATIVE, "Enterovirus C", "A.1")]
    )
    assert membership.suggested_resolution_kind == RESOLUTION_DECISION


def test_queue_ids_are_content_derived_so_a_rerun_does_not_renumber_a_worksheet() -> None:
    first = queue_id("R-SPECIMEN-2", "specimen_type", "conjunctival swab")
    assert first == queue_id("R-SPECIMEN-2", "specimen_type", "conjunctival swab")
    assert first != queue_id("R-SPECIMEN-2", "specimen_type", "rhabdomyosarcoma cell")
    assert first.startswith("Q-") and len(first) == 14


def test_groups_come_out_in_a_stable_order() -> None:
    """Not by size: one group growing would otherwise reshuffle the whole worksheet."""
    rows = [
        declined("specimen_type", "R-SPECIMEN-2", "no_specimen_keyword_in_isolation_source",
                 source, "A.1")
        for source in ("cell culture", "conjunctiva", "brain tissue")
    ]
    groups = build_queue(rows)
    assert [g.queue_id for g in groups] == sorted(g.queue_id for g in groups)


@pytest.mark.slow
def test_the_real_build_produces_the_expected_queue(repository_root: Path, tmp_path: Path) -> None:
    """Pinned so the queue cannot silently grow or shrink between builds."""
    result = build_metadata_layer(repository_root, tmp_path)
    assert result.row_counts["curation_queue_records"] == EXPECTED_QUEUE_WORK_ITEMS
    assert result.row_counts["curation_queue_groups"] == EXPECTED_QUEUE_GROUPS


def test_a_blank_input_is_not_advised_as_a_rule_change() -> None:
    """The queue's biggest group shares only the *absence* of an input.

    ~10,000 records deposit no `/isolation_source`. No pattern change can resolve a record with no
    text to match, so advising `rule_parameter` there was wrong on most of the queue — and it also
    falsified the claim that resolving one group resolves every record in it.
    """
    (group,) = build_queue(
        [declined("specimen_type", "R-SPECIMEN-2", UNRESOLVED_NO_SOURCE, "", "A.1")]
    )
    assert group.suggested_resolution_kind == RESOLUTION_DECISION


def test_every_registry_field_target_is_a_real_ledger_field(repository_root: Path) -> None:
    """A target that is not a ledger `field_name` sends the curator's decision nowhere.

    Nothing checked this, and the map is the queue's whole answer to the D2 failure.
    """
    with (repository_root / "registry/decisions.tsv").open(encoding="utf-8", newline="") as handle:
        known = {row["field_name"] for row in csv.DictReader(handle, delimiter="\t")}
    for canonical, registry_field in REGISTRY_FIELD_FOR_CANONICAL.items():
        assert registry_field in known, (
            f"{canonical} -> {registry_field} is not a field_name any ledger row uses"
        )
