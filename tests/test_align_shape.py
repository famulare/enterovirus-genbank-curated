"""`align.shape`: the declared delta against 2.4.1, and the reason vocabulary behind it.

The delta is the claim that replaces byte parity, so the load-bearing property is that a dropped row
can only be filed under a declared reason — an undeclared drop must raise rather than be absorbed.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, shape
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.contracts import ContractError


def test_shipped_row_ids_tolerates_the_anchored_dialect(tmp_path: Path) -> None:
    """2.4.1's anchored files repeat each id on a `#=GS` line after its sequence. Only the sequence
    line's id should be taken, once."""
    path = tmp_path / "x.sto.gz"
    text = (
        "# STOCKHOLM 1.0\n#=GF SQ 2\n"
        "A09260 ---AC\n#=GS A09260 AC A09260\n"
        "AB061301 --ACG\n#=GS AB061301 AC AB061301\n"
        "#=GC RF ACGTA\n//\n"
    )
    with path.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        gz.write(text.encode("utf-8"))
    assert shape.shipped_row_ids(path) == ("A09260", "AB061301")


def test_shipped_row_ids_reads_the_real_shipped_pv3(repository_root: Path) -> None:
    ids = shape.shipped_row_ids(repository_root / "final/alignments/PV3_unified.sto.gz")
    assert len(ids) == len(set(ids))
    assert len(ids) == 1425, "the shipped PV3_unified row count is a fixed historical fact"


def test_carve_exclusions_finds_the_one_active_exclusion(repository_root: Path) -> None:
    """`AH004344` is the ledger's carve exclusion, and it is the reason the vocabulary entry can
    fire at all. If this returns nothing, `carve_excluded` becomes unreachable."""
    excluded = shape.carve_exclusions(repository_root)
    assert "AH004344" in excluded
    assert excluded["AH004344"]


# --- the drop-reason vocabulary ------------------------------------------------------------------


@pytest.fixture(scope="module")
def records(repository_root: Path) -> dict[str, population_module.AlignedRecord]:
    return population_module.load_all_records(repository_root)


def test_an_undeclared_drop_raises_rather_than_being_absorbed(
    records: dict[str, population_module.AlignedRecord]
) -> None:
    """The one that matters. A shipped row that still satisfies the population rule but is missing
    from the rebuild is a build defect; filing it under any declared reason would hide a regression
    among adjudicated changes."""
    inside = next(
        r.accession for r in records.values()
        if r.virus_group == contract.POLIOVIRUS and r.virus_type == "PV3"
    )
    with pytest.raises(ContractError, match="build defect, not a declared delta"):
        shape._drop_reason(inside, "PV3_unified", records, "PV3", {})


def test_a_record_absent_from_canonical_is_attributed_to_the_carve(
    records: dict[str, population_module.AlignedRecord]
) -> None:
    reason = shape._drop_reason("AH004344", "PV3_unified", records, "PV3", {"AH004344": "why"})
    assert reason == shape.REASON_CARVE_EXCLUDED


def test_a_record_absent_from_canonical_and_from_the_ledger_is_named_as_such(
    records: dict[str, population_module.AlignedRecord]
) -> None:
    reason = shape._drop_reason("NOSUCHACC", "PV3_unified", records, "PV3", {})
    assert reason == shape.REASON_ABSENT_FROM_CANONICAL


def test_group_takes_precedence_over_a_lost_type(
    records: dict[str, population_module.AlignedRecord]
) -> None:
    """`OR538735` both changed group and lost its type, so precedence must be declared rather than
    incidental. Group is coarser, and the one that moved it out of the population."""
    record = records.get("OR538735")
    if record is None:
        pytest.skip("OR538735 is not in this release's canonical metadata")
    assert record.virus_group != contract.POLIOVIRUS
    assert not record.virus_type
    reason = shape._drop_reason("OR538735", "PV3_unified", records, "PV3", {})
    assert reason == shape.REASON_GROUP_MOVED


def test_a_relabelled_serotype_is_named_as_such(
    records: dict[str, population_module.AlignedRecord]
) -> None:
    pv1 = next(
        r.accession for r in records.values()
        if r.virus_group == contract.POLIOVIRUS and r.virus_type == "PV1"
    )
    # Shipped as PV2, curated as PV1: a relabel, not a membership change.
    assert shape._drop_reason(pv1, "PV2_unified", records, "PV2", {}) == (
        shape.REASON_SEROTYPE_RELABELLED
    )


def test_every_declared_reason_is_reachable() -> None:
    """A vocabulary entry nothing can produce is the same anti-pattern as a check that cannot fail,
    so the declared set and the set the code can return must agree."""
    produced = {
        shape.REASON_GROUP_MOVED, shape.REASON_SEROTYPE_RELABELLED,
        shape.REASON_VIRUS_TYPE_LOST, shape.REASON_CARVE_EXCLUDED,
        shape.REASON_ABSENT_FROM_CANONICAL,
    }
    assert produced == set(shape.DROP_REASONS)


# --- the report over a real built artifact --------------------------------------------------------

BUILT = Path(__file__).resolve().parents[1] / "derived/alignments/PV3_unified.sto.gz"


@pytest.mark.skipif(not BUILT.is_file(), reason="PV3_unified has not been built in this tree")
def test_the_report_states_the_delta_for_a_real_artifact(repository_root: Path) -> None:
    report = shape.build_report(
        repository_root, repository_root / "derived/alignments", ("PV3_unified",)
    )
    entry = report["artifacts"]["PV3_unified"]
    delta = entry["delta_vs_2_4_1"]
    assert delta["shipped_rows"] == 1425
    assert delta["rebuilt_rows"] == contract.ARTIFACTS["PV3_unified"].expected_rows
    # The plan predicted +270 / -2 for PV3 from metadata alone, before any alignment was built.
    assert delta["n_added"] == 270
    assert delta["n_dropped"] == 2
    assert set(delta["dropped_by_reason"]) <= set(shape.DROP_REASONS)
    assert entry["shape"]["width_nt"] == 7432
    assert sum(entry["shape"]["block_widths"].values()) == 7432


@pytest.mark.skipif(not BUILT.is_file(), reason="PV3_unified has not been built in this tree")
def test_render_names_every_artifact_it_reports(repository_root: Path) -> None:
    report = shape.build_report(
        repository_root, repository_root / "derived/alignments", ("PV3_unified",)
    )
    text = shape.render(report)
    assert "## PV3_unified" in text
    assert "vs 2.4.1" in text
