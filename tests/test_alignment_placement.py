"""The placement gate: does it separate a scattered row from a contiguous one?

This gate was ported on 2026-08-15 to close a real asymmetry — the repository carried the `--lop`
fix that stops `mafft --addfragments` scattering short sequences, but nothing measured whether the
fix was still working. A parameter is only known-good while something checks it.

The corpus numbers are pinned at the bottom, but the constructed cases matter more: they establish
that the metric would *notice*, which the corpus alone cannot show while every artifact passes.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import placement

# CDS block offsets for the three unified artifacts, from their own build provenance.
CDS_BLOCKS = {
    "NPEV_unified": (738, 7503),
    "EV_unified": (738, 7992),
    "POLIO_unified": (746, 6816),
}
# Measured on release 5.0.0's own artifacts. All three sit far under the 5% ceiling, and well under
# the 3.5% the upstream screen reported after the same fix landed there.
CORPUS_BADLY_PLACED_CEILING = 0.05


def test_a_contiguous_row_scores_one() -> None:
    block = {f"r{i}": "ACGT" * 10 for i in range(10)}
    block["short"] = "-" * 8 + "ACGT" * 4 + "-" * 16
    consensus = placement.consensus_mask(list(block.values()))
    assert placement.occupancy(block["short"], consensus) == 1.0


def test_a_scattered_row_scores_low() -> None:
    """The defect itself: the same residues, spread over the same span.

    Both rows carry 16 residues across 40 columns. The contiguous one fills every consensus column
    it spans; the scattered one spans the same consensus columns and skips three quarters of them.
    """
    block = {f"r{i}": "ACGT" * 10 for i in range(10)}
    block["scattered"] = "".join("A" if i % 4 == 0 else "-" for i in range(40))
    consensus = placement.consensus_mask(list(block.values()))
    value = placement.occupancy(block["scattered"], consensus)
    assert value is not None and value < placement.BADLY_PLACED


def test_a_row_whose_columns_are_all_sparse_is_unmeasurable_not_perfect() -> None:
    """`None`, never 1.0 — and this is the case that actually arises.

    A row alone in a region trivially makes its own columns consensus, so "outside the consensus"
    is not reachable that way. What is reachable is the private-insertion case: `PX242045` opens
    2,169 columns in `NPEV_unified` that 14,217 other rows span and none fill. Every such column
    fails the quorum, so a row living only in them spans no consensus column at all. Scoring that
    1.0 would let the widest insertion owners certify their own placement.
    """
    block = {f"r{i}": "AAAA" + "-" * 4 + "AAAA" for i in range(20)}
    block["private"] = "-" * 4 + "AAAA" + "-" * 4
    consensus = placement.consensus_mask(list(block.values()))
    assert consensus[4:8] == [False] * 4
    assert placement.occupancy(block["private"], consensus) is None


def test_an_all_gap_row_has_no_span() -> None:
    assert placement.row_span("----") == (-1, -1)
    assert placement.occupancy("----", [True] * 4) is None


def test_the_gate_fails_when_the_addon_tier_scatters() -> None:
    """Constructed to breach the ceiling, so the failure path is exercised rather than assumed."""
    block = {f"b{i}": "ACGT" * 10 for i in range(20)}
    for i in range(10):
        block[f"a{i}"] = "".join("A" if j % 4 == 0 else "-" for j in range(40))
    summary, failures = placement.check_addon_placement(
        block, lambda acc: "addon" if acc.startswith("a") else "backbone", "probe"
    )
    assert summary["badly_placed_share"] > placement.MAX_BADLY_PLACED_SHARE
    assert failures and "scatter" in failures[0]


def test_the_gate_passes_when_the_addon_tier_is_contiguous() -> None:
    """Negative control. A gate that fired on everything would say nothing."""
    block = {f"b{i}": "ACGT" * 10 for i in range(20)}
    for i in range(10):
        block[f"a{i}"] = "-" * 8 + "ACGT" * 4 + "-" * 16
    summary, failures = placement.check_addon_placement(
        block, lambda acc: "addon" if acc.startswith("a") else "backbone", "probe"
    )
    assert not failures
    assert summary["median_occupancy"] == 1.0


def read_cds_block(path: Path, lo: int, width: int) -> dict[str, str]:
    block: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        accession, chunks = None, []
        for line in handle:
            if line.startswith(">"):
                if accession:
                    block[accession] = "".join(chunks)[lo : lo + width]
                accession = line[1:].strip().split()[0].split(".")[0]
                chunks = []
            else:
                chunks.append(line.strip())
        if accession:
            block[accession] = "".join(chunks)[lo : lo + width]
    return block


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(CDS_BLOCKS))
def test_the_built_artifacts_place_their_addon_rows_well(
    repository_root: Path, name: str
) -> None:
    """Placement quality, which is this gate's only claim.

    It is deliberately *not* a claim about width. An earlier version of this docstring read the
    clean placement result as an explanation for `NPEV_unified` being 15,435 nt against 2.4.1's
    8,502 — "narrower was worse". Measured, that is false: 2.4.1 carries the same 43,110 N residues
    in 7,677 CDS columns with zero all-N columns. The width was ambiguity padding, now removed by
    `codon.drop_unsequenced_codon_columns`; the `--lop` fix this gate watches bought 0.13 pp of
    placement and no width at all.
    """
    from enterovirus_genbank_curated.align import population

    built = repository_root / "final/alignments" / f"{name}_aln.fasta.gz"
    if not built.is_file():
        pytest.skip(f"{name} not promoted yet")
    lo, width = CDS_BLOCKS[name]
    records = population.load_all_records(repository_root)
    tier = {key.split(".")[0]: value.tier for key, value in records.items()}
    summary, failures = placement.check_addon_placement(
        read_cds_block(built, lo, width), lambda acc: tier.get(acc, "backbone"), name
    )
    assert not failures, failures
    assert summary["badly_placed_share"] <= CORPUS_BADLY_PLACED_CEILING
    assert summary["median_occupancy"] == 1.0
