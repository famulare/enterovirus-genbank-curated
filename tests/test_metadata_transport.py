"""Tests for the canonical metadata transport.

The slow gate used to rebuild the carve and compare every transported cell to the shipped release.
That comparison retired on 2026-08-01, when `final/` became this pipeline's own output — see
`oracle/parity.py`'s module docstring. What replaced it makes a claim that survives the change of
destination: the build declines exactly where this repository declares it declines, checked against
a fresh build with no release involved.

The fast tests cover the behaviour the corpus cannot falsify on its own: the closed-form geo rule's
edge cases, and the status filter on ledger exclusions, which today's ledger happens not to exercise
because none of its retired or superseded rows is an exclusion.
"""

from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import DECISION_COLUMNS
from enterovirus_genbank_curated.derive.geo import parse_geo_loc_name
from enterovirus_genbank_curated.derive.metadata import UNDECLARED_EXCLUSIONS
from enterovirus_genbank_curated.oracle.parity import (
    DECLARED_DECLINES,
    GUARD_PASS_MARKER,
    UNRESOLVED_ENGINEERED_ROWS,
    UNRESOLVED_PARTITION_ROWS,
    verify_metadata_declines,
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
def test_the_build_declines_exactly_where_it_declares_it_declines(repository_root: Path) -> None:
    observed = verify_metadata_declines(repository_root)
    assert observed == DECLARED_DECLINES

    # Both partition columns decline on the same population, and never on a different one.
    assert observed["virus_group"] == UNRESOLVED_PARTITION_ROWS
    assert observed["curation_status"] == UNRESOLVED_PARTITION_ROWS

    # `engineered_or_construct` is declared as a named zero rather than omitted. R-CONSTRUCT-2
    # declined only on the two records a curator had left open, and both were closed on 2026-07-31;
    # the key stays so the next record to decline fails this gate instead of appearing as a new key
    # nobody pinned.
    assert UNRESOLVED_ENGINEERED_ROWS == 0
    assert observed["engineered_or_construct"] == 0

    # The nine records the release excludes and the build carves are still carved, and are still
    # counted in these declines rather than silently dropped.
    assert len(UNDECLARED_EXCLUSIONS) == 9


@pytest.mark.slow
def test_the_guarded_declines_verb_actually_runs(repository_root: Path) -> None:
    """The guarded path needs its own process, and needs exercising.

    Its predecessor, `parity-metadata --guard-inputs`, was dead for its whole existence and nothing
    noticed: the reader demanded nine release columns while the writer wrote ten, so the guarded
    path raised on every run while the unguarded one — which keeps rows in memory and never reads
    the artifact back — passed. Shelling out is the only way to cover it, since the guard installs
    an audit hook that cannot be uninstalled.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "enterovirus_genbank_curated.cli", "check-declines",
            "--repository-root", str(repository_root), "--guard-inputs",
        ],
        capture_output=True, text=True, cwd=repository_root, timeout=1800, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "declared declines: PASS" in result.stdout
    # The build ran in a guarded child, and the parent requires that child to have said so.
    assert GUARD_PASS_MARKER in result.stdout
