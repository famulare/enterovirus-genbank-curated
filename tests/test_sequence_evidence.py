"""The VP1 divergence view: the measurement `poliovirus_classification` was decided from.

R-CLASS-2 has compared VP1 nucleotide divergence to the thresholds the rule catalog publishes since
the sequence stage landed, and until now the number it compared was recomputed on every build and
then dropped. The release shipped the verdicts and withheld the evidence behind them, which is the
same shape of defect as a blank cell that cannot say whether a rule chose it or declined it.

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
from enterovirus_genbank_curated.derive.evidence import EVIDENCE_COLUMNS
from enterovirus_genbank_curated.export.audit import VP1_DIVERGENCE_RELATIVE, write_vp1_divergence
from enterovirus_genbank_curated.oracle.parity import SHIPPED_SEQUENCE_EVIDENCE

CLASSIFICATION_FIELD = "poliovirus_classification"

# The only two columns the shipped table and this one have in common. Everything else about the two
# differs, which is the whole argument for the separate filename.
SHARED_WITH_SHIPPED = {"accession", "version"}
SHIPPED_COLUMN_COUNT = 21

# 7,728 = 24,308 carved records
#         − 14,669 whose organism name names no serotype, so there is no reference to measure
#           against; `derive/evidence.py` will not serotype by sequence to invent one
#         − 1,708 where no 12-mer diagonal inside VP1 clears `MIN_DIAGONAL_ANCHORS` (754 of those
#           are under 300 nt of sequence in total, so they could never have reached `MIN_VP1_NT`)
#         − 194 that do seed a diagonal but overlap VP1 by less than `MIN_VP1_NT`
#         − 9 whose best diagonal sits above `IMPLAUSIBLE_DIVERGENCE_PCT`, which is not a
#           measurement of homologous sequence and is reported as nothing rather than a big number.
EXPECTED_VP1_DIVERGENCE_ROWS = 7728


def read_view(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        return list(reader.fieldnames or ()), list(reader)


def measurement(serotype: str, pct: str, compared: str, strand: str = "+") -> dict[str, str]:
    return {
        "vp1_reference_serotype": serotype,
        "vp1_reference_version": f"AY18421{serotype[-1]}.1",
        "vp1_divergence_pct": pct,
        "vp1_compared_nt": compared,
        "vp1_strand": strand,
    }


def cited_measurement(row: dict[str, str]) -> str:
    """The string R-CLASS-2 composes for `source_value` when the sequence decided the call."""
    return (
        f"{row['vp1_divergence_pct']}% over {row['vp1_compared_nt']} nt vs "
        f"{row['vp1_reference_version']}"
    )


def test_the_writer_derives_the_accession_and_keeps_the_carves_row_order(tmp_path: Path) -> None:
    """Insertion order, not a re-sort.

    `measure_sequence_evidence` walks the carved rows, so its keys already arrive in the canonical
    table's order. Sorting them again here would create a second ordering to keep in step with the
    first, and the two would eventually disagree. The versions below are deliberately given in an
    order a string sort would reverse.
    """
    written = write_vp1_divergence(
        tmp_path,
        {
            "MZ000002.1": measurement("PV3", "18.402", "903", strand="-"),
            "AB000001.2": measurement("PV1", "0.111", "903"),
        },
    )
    assert written == 2
    header, rows = read_view(tmp_path / VP1_DIVERGENCE_RELATIVE)
    assert tuple(header) == EVIDENCE_COLUMNS
    assert [row["version"] for row in rows] == ["MZ000002.1", "AB000001.2"]
    # The accession is split back out of the version rather than carried twice in memory, including
    # for a version suffix that is not `.1`.
    assert [row["accession"] for row in rows] == ["MZ000002", "AB000001"]
    assert rows[0]["vp1_strand"] == "-"
    assert rows[1]["vp1_divergence_pct"] == "0.111"


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
    assert len(EVIDENCE_COLUMNS) == 7
    # Not a projection of the shipped table the way the rule view is a projection of `rules.tsv.gz`:
    # only the two identity columns are shared, so none of the five measurement columns exists there
    # under a name this table could be read as filling.
    assert set(header) & set(EVIDENCE_COLUMNS) == SHARED_WITH_SHIPPED
    # And the shipped table covers the whole carve rather than the named-serotype subset, so even a
    # column-name coincidence would not make the two interchangeable.
    assert len(rows) > 3 * EXPECTED_VP1_DIVERGENCE_ROWS


@pytest.mark.slow
def test_the_real_build_writes_the_measurement_r_class_2_cited(
    repository_root: Path, tmp_path: Path
) -> None:
    """The gate: a build produces the artifact, and it carries the numbers the rule actually used.

    A view recomputed for the file would be worth much less — it could agree with the classification
    rule by construction and then drift from it silently. So every provenance row R-CLASS-2 resolved
    from the sequence is required to cite exactly the divergence, compared length and reference
    version this artifact records for that record, in the string the rule composed. One measurement
    per record, and both readers see the same one.
    """
    result = build_metadata_layer(repository_root, tmp_path)
    assert result.row_counts["vp1_divergence_rows"] == EXPECTED_VP1_DIVERGENCE_ROWS

    header, rows = read_view(tmp_path / VP1_DIVERGENCE_RELATIVE)
    assert tuple(header) == EVIDENCE_COLUMNS
    assert len(rows) == EXPECTED_VP1_DIVERGENCE_ROWS

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
            f"audit/vp1_divergence.tsv.gz records for it"
        )
