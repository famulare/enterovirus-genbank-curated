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
import subprocess
import sys
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import DECISION_COLUMNS
from enterovirus_genbank_curated.derive.geo import parse_geo_loc_name
from enterovirus_genbank_curated.derive.metadata import (
    SEQUENCE_RESCUED_INCLUSIONS,
    UNDECLARED_EXCLUSIONS,
)
from enterovirus_genbank_curated.oracle.parity import (
    GUARD_PASS_MARKER,
    SUPERSEDED_FIELD_DELTAS,
    SUPERSEDED_FIELD_WITNESSES,
    UNRESOLVED_ORIGIN_ROWS,
    UNRESOLVED_PARTITION_ROWS,
    UNRESOLVED_SPECIMEN_ROWS,
    verify_metadata_parity,
    witness_digest,
)
from enterovirus_genbank_curated.registry.decisions import load_excluded_accessions


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
    # upstream field and value it came from, the winning rule, and the branch label. `virus_group`
    # is the first field where `manual_override` is non-trivial: it is TRUE on exactly the seventeen
    # records the ledger's `is_poliovirus` decisions resolve, so this also proves the decision
    # reaches the provenance row rather than merely existing in the ledger.
    assert provenance.fields == (
        "collection_date",
        "collection_date_precision",
        "curation_status",
        "locality",
        "sample_origin",
        "specimen_type",
        "virus_group",
    )
    # Per field, how many of the 24,284 shared records the rule resolves. Spelled out rather than
    # computed, because the declined counts below are over the 24,285 *built* rows: AF326751.2
    # deposits no `/isolation_source`, so its specimen_type decline is counted there but is not a
    # shared row. That one-record difference is exactly the kind of thing a single total would hide.
    resolved_per_field = {
        "locality": 24284,
        "collection_date": 24284,
        "collection_date_precision": 24284,
        "virus_group": 24284 - UNRESOLVED_PARTITION_ROWS,
        "curation_status": 24284 - UNRESOLVED_PARTITION_ROWS,
        "specimen_type": 24284 - (UNRESOLVED_SPECIMEN_ROWS - 1),
        "sample_origin": 24284 - UNRESOLVED_ORIGIN_ROWS,
    }
    assert set(resolved_per_field) == set(provenance.fields)
    assert provenance.compared_rows == sum(resolved_per_field.values())
    assert sum(provenance.basis_counts.values()) == provenance.compared_rows
    # Counted as (version, field) keys. The seventeen records the carve cannot reach are missing one
    # row per projected field, since the release has a row for all six.
    assert provenance.absent_from_build == len(SEQUENCE_RESCUED_INCLUSIONS) * len(
        provenance.fields
    )
    # The converse is not symmetric, and the asymmetry is the point: AF326751.2 contributes only the
    # five rows its rules *resolve*. It deposits no `/isolation_source`, so specimen_type declines,
    # and a declined row is not compared at all — so it cannot be counted as a missing comparison.
    assert len(UNDECLARED_EXCLUSIONS) == 1
    assert provenance.absent_from_release == len(provenance.fields) - 1

    # Both partition columns decline on the same population, and never on a different one.
    assert provenance.unresolved_by_field == {
        "virus_group": UNRESOLVED_PARTITION_ROWS,
        "curation_status": UNRESOLVED_PARTITION_ROWS,
        "specimen_type": UNRESOLVED_SPECIMEN_ROWS,
        "sample_origin": UNRESOLVED_ORIGIN_ROWS,
    }

    # The two date columns deliberately differ from the release, by exactly the declared amount.
    # A delta that cannot be stated as a number is not a declared delta.
    assert provenance.superseded_deltas == SUPERSEDED_FIELD_DELTAS


def test_the_witness_gate_catches_a_substituted_disagreement() -> None:
    """A per-column *count* lets one record be fixed while another regresses.

    A review demonstrated it: pattern-matching `GQ331952.1` around to the shipped value while
    regressing `AB162759.1` kept `specimen_type`'s `final_value` delta at 1 and `parity-metadata`
    reported PASS, with the release now disagreeing on a different record than the one declared. The
    declared witness is what closes that, so this test substitutes one triple for another and
    requires the digest to move.
    """
    declared = ["GQ331952.1|environmental|stool"]
    substituted = ["AB162759.1|environmental|stool"]
    assert witness_digest(declared) != witness_digest(substituted)
    # Order must not matter, or a reordered build would look like a substitution.
    pair = ["A.1|x|y", "B.1|p|q"]
    assert witness_digest(pair) == witness_digest(list(reversed(pair)))


def test_every_declared_witness_names_a_column_with_a_declared_count() -> None:
    """A witness for an undeclared column would be compared against nothing."""
    for field, columns in SUPERSEDED_FIELD_WITNESSES.items():
        assert field in SUPERSEDED_FIELD_DELTAS
        for column, digest in columns.items():
            assert SUPERSEDED_FIELD_DELTAS[field][column] > 0, (
                f"{field}.{column} declares a witness but a zero count"
            )
            assert len(digest) == 16


@pytest.mark.slow
def test_the_guarded_parity_verb_actually_runs(repository_root: Path) -> None:
    """`parity-metadata --guard-inputs` was dead for its whole existence and nothing noticed.

    The reader demanded the nine release columns while the writer wrote ten, so the guarded path
    raised on every run. Only the unguarded path was exercised — it keeps rows in memory and never
    reads the artifact back, so it could not see the mismatch. Shelling out is the only way to cover
    this: the guard installs an audit hook that cannot be uninstalled, so it needs its own process.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "enterovirus_genbank_curated.cli", "parity-metadata",
            "--repository-root", str(repository_root), "--guard-inputs",
        ],
        capture_output=True, text=True, cwd=repository_root, timeout=1800, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "metadata parity: PASS" in result.stdout
    assert "provenance parity: PASS" in result.stdout
    # The build ran in a guarded child, and the parent requires that child to have said so.
    assert GUARD_PASS_MARKER in result.stdout
