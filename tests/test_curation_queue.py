"""The curation queue: what a rule's decline turns into.

The queue is the half of honest declining that makes it useful. Without it, `unresolved_reason` is a
note nobody acts on and the rewrite just ships a permanently emptier table than the release.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.build import build_metadata_layer
from enterovirus_genbank_curated.curate.queue import (
    RESOLUTION_DECISION,
    RESOLUTION_RULE_PARAMETER,
    build_queue,
    queue_id,
)
from enterovirus_genbank_curated.derive.partition import (
    UNRESOLVED_FOLLOWS_PARTITION,
    UNRESOLVED_UNINFORMATIVE,
)

# Summed across fields, so a record needing two decisions counts twice — this is a measure of work,
# not of records. 12,684 specimen_type + 4,483 sample_origin + 1,733 partition = 18,900 declined
# cells, less the 1,626 sample_origin declines that are themselves consequences of an undecided
# partition. `curation_status` declines on the same 1,733 as `virus_group` and is absent for that
# same reason: it follows the partition rather than needing a decision of its own.
EXPECTED_QUEUE_WORK_ITEMS = 17274
EXPECTED_QUEUE_GROUPS = 181


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
