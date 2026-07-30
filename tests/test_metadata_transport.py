"""Tests for the canonical metadata transport.

Deliberately three tests. The slow one is the gate — it rebuilds the carve from `raw/` and compares
every transported cell to the shipped release, so it already covers column selection, row-set
membership, row order, and the ledger's exclusions as they actually stand. The two fast tests cover
the only behaviour the corpus cannot currently falsify: the closed-form geo rule's edge cases, and
the status filter on ledger exclusions, which today's ledger happens not to exercise because none
of its retired or superseded rows is an exclusion.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import DECISION_COLUMNS
from enterovirus_genbank_curated.derive.metadata import (
    SEQUENCE_RESCUED_INCLUSIONS,
    UNDECLARED_EXCLUSIONS,
    load_excluded_accessions,
    parse_geo_loc_name,
)
from enterovirus_genbank_curated.oracle.parity import verify_metadata_parity


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ("", "", "")),
        ("Pakistan", ("Pakistan", "", "")),
        ("Pakistan:", ("Pakistan", "", "")),
        # No comma means no sub-admin1 detail, so locality would only repeat admin1:
        # R-GEO-LOCALITY-1 blanks it.
        ("Pakistan: Sindh", ("Pakistan", "Sindh", "")),
        # With detail, locality keeps the whole remainder and so still starts with admin1.
        ("Pakistan: Sindh, Karachi", ("Pakistan", "Sindh", "Sindh, Karachi")),
        ("Pakistan: Sindh, Karachi, UC-4", ("Pakistan", "Sindh", "Sindh, Karachi, UC-4")),
        # Only the first colon separates; a second one is region text.
        ("Congo: Kinshasa: Limete", ("Congo", "Kinshasa: Limete", "")),
    ],
)
def test_geo_loc_name_splits_into_country_admin1_and_sub_admin1_detail(
    value: str, expected: tuple[str, str, str]
) -> None:
    parsed = parse_geo_loc_name(value)
    assert (parsed.country, parsed.admin1, parsed.locality) == expected


def test_only_active_ledger_rows_exclude_a_record(tmp_path: Path) -> None:
    """A withdrawn exclusion must not keep excluding.

    `status` is the curator's way of taking a decision back. Honouring a `retired` or `superseded`
    exclusion would silently hold a record out of the carve after the reason for holding it out was
    revoked — and no row in the shipped ledger is in that state, so the corpus gate cannot catch it.
    """
    rows = [
        ("D-000000000001", "membership_exclusion", "active"),
        ("D-000000000002", "membership_exclusion", "retired"),
        ("D-000000000003", "carve_exclusion", "superseded"),
        ("D-000000000004", "carve_exclusion", "active"),
        ("D-000000000005", "manual_override", "active"),
    ]
    path = tmp_path / "decisions.tsv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(DECISION_COLUMNS), delimiter="\t")
        writer.writeheader()
        for decision_id, decision_type, status in rows:
            accession = f"AF{decision_id[-6:]}"
            writer.writerow(
                {
                    "decision_id": decision_id,
                    "decision_type": decision_type,
                    "subject_key": accession,
                    "accession": accession,
                    "field_name": "membership_excluded",
                    "new_value": "TRUE",
                    "reason": "test",
                    "evidence_reference": "",
                    "confirmed_by": "curator",
                    "source_artifact": "test",
                    "status": status,
                    "effective_from": "",
                    "effective_through": "",
                    "notes": "",
                }
            )

    assert load_excluded_accessions(path) == {"AF000001", "AF000004"}


@pytest.mark.slow
def test_metadata_transport_matches_the_shipped_canonical(repository_root: Path) -> None:
    parity, provenance = verify_metadata_parity(repository_root)
    assert parity.compared_rows == 24284
    assert len(parity.compared_columns) == 13
    assert set(parity.absent_from_build) == SEQUENCE_RESCUED_INCLUSIONS
    assert set(parity.absent_from_release) == UNDECLARED_EXCLUSIONS

    # Provenance for every implemented rule, compared on all nine shipped columns — value, the
    # upstream field and value it came from, the winning rule, and the branch label.
    assert provenance.fields == ("locality",)
    assert provenance.compared_rows == 24284
    assert sum(provenance.basis_counts.values()) == provenance.compared_rows
    assert provenance.absent_from_build == len(SEQUENCE_RESCUED_INCLUSIONS)
    assert provenance.absent_from_release == len(UNDECLARED_EXCLUSIONS)
