"""The classification divergence view: the measurement `poliovirus_classification` was decided from.

R-CLASS-2 has compared Sabin divergence to the thresholds the rule catalog publishes since the
sequence stage landed, and until now the number it compared was recomputed on every build and then
dropped. The release shipped the verdicts and withheld the evidence behind them, which is the same
shape of defect as a blank cell that cannot say whether a rule chose it or declined it.

The view carries its own name rather than the shipped `sequence_evidence.tsv.gz`, and
`test_the_shipped_sequence_evidence_is_a_different_table` is what keeps that decision from becoming
folklore: it re-measures the schema mismatch that justifies the separate name on every run. If a
later stage ever does produce the shipped twenty-one columns, that test fails and the name is
reconsidered rather than inherited.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path

import pytest

from enterovirus_genbank_curated.build import build_metadata_layer
from enterovirus_genbank_curated.derive.classification import (
    DEFINITION_FIELD,
    EVIDENCE_DIVERGENCE,
)
from enterovirus_genbank_curated.derive.evidence import (
    BASIS_CAPSID,
    BASIS_CAPSID_BY_MEMBERSHIP_BAND,
    BASIS_VP1,
    BASIS_VP1_BY_MEMBERSHIP_BAND,
    EVIDENCE_COLUMNS,
)
from enterovirus_genbank_curated.export.audit import (
    CLASSIFICATION_DIVERGENCE_RELATIVE,
    write_classification_divergence,
)
from enterovirus_genbank_curated.oracle.parity import SHIPPED_SEQUENCE_EVIDENCE

CLASSIFICATION_FIELD = "poliovirus_classification"

# The only two columns the shipped table and this one have in common. Everything else about the two
# differs, which is the whole argument for the separate filename.
SHARED_WITH_SHIPPED = {"accession", "version"}
SHIPPED_COLUMN_COUNT = 21

# 7,728 by VP1 + 159 by the capsid fallback = 7,887.
#
# 7,728 = 24,308 carved records
#         − 14,669 whose organism name names no serotype, so there is no reference to measure
#           against; `derive/evidence.py` will not serotype by sequence to invent one
#         − 1,708 where no 12-mer diagonal inside VP1 clears `MIN_DIAGONAL_ANCHORS` (754 of those
#           are under 300 nt of sequence in total, so they could never have reached `MIN_VP1_NT`)
#         − 194 that do seed a diagonal but overlap VP1 by less than `MIN_VP1_NT`
#         − 9 whose best diagonal sits above `IMPLAUSIBLE_DIVERGENCE_PCT`, which is not a
#           measurement of homologous sequence and is reported as nothing rather than a big number.
#
# 159 = of the 1,911 records VP1 does not reach, 366 get any capsid-nt diagonal at all; of those,
#       162 clear `MIN_CAPSID_NT`; of those, 3 fail `_capsid_homogeneous` — each one carrying a
#       single-nucleotide break the module docstring diagnoses, not a real divergence.
#
# 7,773 by VP1 + 175 by the capsid fallback = 7,948, when `MIN_VP1_NT`/`MIN_CAPSID_NT` dropped from
# 300 to 50 nt on 2026-07-31 (MAD-VDPV's own `MIN_SEROTYPE_COMPARED_NT`). The floor alone would have
# opened more than this: the chunked-homogeneity guard extended to VP1 for the newly-opened sub-300
# nt territory declines three records that would otherwise measure — `AY320423`, `JN092124`,
# `AY365233` — where a single bad base in the deposit (not a real indel; VP1 has none relative to
# Sabin, but the artifact is in the read, not the biology) corrupted a 171-225 nt window enough to
# move the divergence 15-24 percentage points from MAD-VDPV's own alignment.
#
# +45 VP1 = 44 genuinely new + `AJ783799`, already measured at 0.660% via the capsid fallback (303
# nt, just over the old 300 nt floor), which now measures 0.669% via VP1 alone (299 nt, under the
# old floor but over the new one) instead — same tier either way, so `Sabin-like` does not move; only
# which basis reached it does. +16 capsid = 17 genuinely new − the one `AJ783799` no longer needs.
# Of the 61 genuinely-new accessions (44 + 17), 60 were previously declined and now agree with the
# shipped classification; the 61st already had an active ledger decision, so its classification was
# unaffected — it simply has evidence to cite where it had none before.
EXPECTED_VP1_ROWS = 7773
EXPECTED_CAPSID_FALLBACK_ROWS = 175
# 392 VP1 + 7 capsid, 2026-08-01: `measure_poliovirus_membership_band` identifies a serotype by
# capsid-AA distance for every organism-uninformative record that clears its 8%/15% band, and
# `measure_sequence_evidence` measures VP1/capsid divergence against that serotype wherever the name
# never named one — 470 records banded, 399 of them `poliovirus`-banded with enough sequence to
# measure. Far more than the 138 records this actually changes a `poliovirus_classification` value
# for: most of the 399 already carry an active ledger classification decision, which still wins
# ahead of this measurement in `derive/classification.py`'s own precedence, so the measurement is
# computed and cited in the audit trail but does not decide the value. Measuring it anyway is the
# same "no ledger-awareness" choice `measure_sequence_evidence` already makes for every name-
# serotyped record with an active decision.
EXPECTED_MEMBERSHIP_BAND_VP1_ROWS = 392
EXPECTED_MEMBERSHIP_BAND_CAPSID_ROWS = 7
EXPECTED_DIVERGENCE_ROWS = (
    EXPECTED_VP1_ROWS
    + EXPECTED_CAPSID_FALLBACK_ROWS
    + EXPECTED_MEMBERSHIP_BAND_VP1_ROWS
    + EXPECTED_MEMBERSHIP_BAND_CAPSID_ROWS
)


def read_view(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        return list(reader.fieldnames or ()), list(reader)


def measurement(
    serotype: str, pct: str, compared: str, basis: str, strand: str = "+"
) -> dict[str, str]:
    return {
        "reference_serotype": serotype,
        "reference_version": f"AY18421{serotype[-1]}.1",
        "divergence_pct": pct,
        "compared_nt": compared,
        "strand": strand,
        "basis": basis,
    }


def cited_measurement(row: dict[str, str]) -> str:
    """The string R-CLASS-2 composes for `source_value` when the sequence decided the call."""
    return (
        f"{row['divergence_pct']}% over {row['compared_nt']} nt of {row['basis']} vs "
        f"{row['reference_version']}"
    )


def test_the_writer_derives_the_accession_and_keeps_the_carves_row_order(tmp_path: Path) -> None:
    """Insertion order, not a re-sort.

    `measure_sequence_evidence` walks the carved rows, so its keys already arrive in the canonical
    table's order. Sorting them again here would create a second ordering to keep in step with the
    first, and the two would eventually disagree. The versions below are deliberately given in an
    order a string sort would reverse.
    """
    written = write_classification_divergence(
        tmp_path,
        {
            "MZ000002.1": measurement("PV3", "18.402", "903", BASIS_VP1, strand="-"),
            "AB000001.2": measurement("PV1", "0.111", "903", BASIS_VP1),
        },
    )
    assert written == 2
    header, rows = read_view(tmp_path / CLASSIFICATION_DIVERGENCE_RELATIVE)
    assert tuple(header) == EVIDENCE_COLUMNS
    assert [row["version"] for row in rows] == ["MZ000002.1", "AB000001.2"]
    # The accession is split back out of the version rather than carried twice in memory, including
    # for a version suffix that is not `.1`.
    assert [row["accession"] for row in rows] == ["MZ000002", "AB000001"]
    assert rows[0]["strand"] == "-"
    assert rows[1]["divergence_pct"] == "0.111"


def test_the_shipped_sequence_evidence_is_a_different_table(repository_root: Path) -> None:
    """Why this is not written as `audit/sequence_evidence.tsv.gz`, measured rather than asserted.

    The release's table is twenty-one columns of sequence-derived evidence over every carved record:
    a sequence serotype and its confidence, a classification tier and basis, capsid amino-acid
    p-distance, frameshift and recombination flags, an independent enterovirus type call. This stage
    produces one of those measurements over a third of the records. If the two ever converge, the
    honest move is to write the shipped name and gate against the shipped bytes, so the mismatch
    that justifies the separate name is checked here rather than left in a comment nobody reruns.
    """
    header, rows = read_view(repository_root / SHIPPED_SEQUENCE_EVIDENCE)
    assert len(header) == SHIPPED_COLUMN_COUNT
    assert len(EVIDENCE_COLUMNS) == 8
    # Not a projection of the shipped table the way the rule view is a projection of `rules.tsv.gz`:
    # only the two identity columns are shared, so none of the measurement columns exists there
    # under a name this table could be read as filling.
    assert set(header) & set(EVIDENCE_COLUMNS) == SHARED_WITH_SHIPPED
    # And the shipped table covers the whole carve rather than the named-serotype subset, so even a
    # column-name coincidence would not make the two interchangeable. The margin dropped from 3x to
    # 2x on 2026-08-01, when the membership-band serotype fallback grew `EXPECTED_DIVERGENCE_ROWS` to
    # within a third of the whole carve; still comfortably true, since this view only ever covers
    # name- or band-serotyped records and the shipped one covers every carved row.
    assert len(rows) > 2 * EXPECTED_DIVERGENCE_ROWS


@pytest.mark.slow
def test_the_real_build_writes_the_measurement_r_class_2_cited(
    repository_root: Path, tmp_path: Path
) -> None:
    """The gate: a build produces the artifact, and it carries the numbers the rule actually used.

    A view recomputed for the file would be worth much less — it could agree with the classification
    rule by construction and then drift from it silently. So every provenance row R-CLASS-2 resolved
    from the sequence is required to cite exactly the divergence, compared length, basis and
    reference version this artifact records for that record, in the string the rule composed. One
    measurement per record, and both readers see the same one.
    """
    result = build_metadata_layer(repository_root, tmp_path)
    assert result.row_counts["classification_divergence_rows"] == EXPECTED_DIVERGENCE_ROWS

    header, rows = read_view(tmp_path / CLASSIFICATION_DIVERGENCE_RELATIVE)
    assert tuple(header) == EVIDENCE_COLUMNS
    assert len(rows) == EXPECTED_DIVERGENCE_ROWS

    by_basis = {
        BASIS_VP1: 0,
        BASIS_CAPSID: 0,
        BASIS_VP1_BY_MEMBERSHIP_BAND: 0,
        BASIS_CAPSID_BY_MEMBERSHIP_BAND: 0,
    }
    for row in rows:
        by_basis[row["basis"]] += 1
    assert by_basis[BASIS_VP1] == EXPECTED_VP1_ROWS
    assert by_basis[BASIS_CAPSID] == EXPECTED_CAPSID_FALLBACK_ROWS
    assert by_basis[BASIS_VP1_BY_MEMBERSHIP_BAND] == EXPECTED_MEMBERSHIP_BAND_VP1_ROWS
    assert by_basis[BASIS_CAPSID_BY_MEMBERSHIP_BAND] == EXPECTED_MEMBERSHIP_BAND_CAPSID_ROWS

    # Every measured record is a carved record, and they appear in the carve's own row order.
    measured = [row["version"] for row in rows]
    assert measured == [row["version"] for row in result.rows if row["version"] in set(measured)]

    composed = {row["version"]: cited_measurement(row) for row in rows}
    from_sequence = [
        row
        for row in result.provenance
        if row["canonical_field"] == CLASSIFICATION_FIELD
        and not row["unresolved_reason"]
        and row["source_field"] in (EVIDENCE_DIVERGENCE, DEFINITION_FIELD)
    ]
    assert from_sequence, "no classification row was decided from the sequence at all"
    for row in from_sequence:
        assert composed.get(row["version"]) == row["source_value"], (
            f"{row['version']} cites {row['source_value']!r}, which is not the measurement "
            f"audit/classification_divergence.tsv.gz records for it"
        )
