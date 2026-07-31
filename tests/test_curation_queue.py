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
EXPECTED_QUEUE_WORK_ITEMS = 28496
# 28,496 when R-CLASS-2 landed: 3,425 `poliovirus_classification` declines join, 1,832 of them
# records whose virus group is undecided and so already in the queue under `virus_group`. A record
# needing two decisions counts twice here on purpose — this is a measure of work, not of records.
# One group, not two: both declined records deposit `division=PAT`, and the queue groups by the
# input the rule examined, so the pair the curator left open arrives as one question. That is the
# grouping working — an answer to it is one adjudication covering both.
EXPECTED_QUEUE_GROUPS = 299


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
