"""The placement gate: does it separate a scattered row from a contiguous one?

This gate was ported on 2026-08-15 to close a real asymmetry — the repository carried the `--lop`
fix that stops `mafft --addfragments` scattering short sequences, but nothing measured whether the
fix was still working. A parameter is only known-good while something checks it.

The corpus numbers are pinned at the bottom, but the constructed cases matter more: they establish
that the metric would *notice*, which the corpus alone cannot show while every artifact passes.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import placement

# CDS block offsets for the three unified artifacts, read from their own build provenance rather
# than copied out of it. They were copied until 2026-08-17, and every one of the three went stale
# the first time a rebuild changed a block width — so the gate below was slicing past the end of the
# CDS into the 3'NCR and measuring privateness over the wrong columns. A coordinate this file cannot
# derive is a coordinate this file will eventually get wrong.
CDS_BLOCK_NAMES = ("NPEV_unified", "EV_unified", "POLIO_unified")


def cds_block_bounds(repository_root: Path, name: str) -> tuple[int, int]:
    """`(offset of the CDS block, its width)` for one artifact, from its provenance."""
    provenance = json.loads(
        (repository_root / "final/alignments" / f"{name}.provenance.json").read_text()
    )
    widths = provenance["block_widths"]
    return widths["5ncr"], widths["cds"]
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
@pytest.mark.parametrize("name", sorted(CDS_BLOCK_NAMES))
def test_the_built_artifacts_place_their_addon_rows_well(
    repository_root: Path, name: str
) -> None:
    """Placement quality, which is this gate's only claim.

    It is deliberately *not* a claim about width. An earlier version of this docstring read the
    clean placement result as an explanation for `NPEV_unified` being 15,435 nt against 2.4.1's
    8,502 — "narrower was worse". Measured, that is false: 2.4.1 carries the same 43,110 N residues
    in 7,677 CDS columns with zero all-N columns. The width was ambiguity padding, since removed by
    `codon.drop_unsequenced_codon_columns` — the shipped CDS is 7,503 columns with 25,155 N — and
    the `--lop` fix this gate watches bought 0.13 pp of placement and no width at all.
    """
    from enterovirus_genbank_curated.align import population

    built = repository_root / "final/alignments" / f"{name}_aln.fasta.gz"
    if not built.is_file():
        pytest.skip(f"{name} not promoted yet")
    lo, width = cds_block_bounds(repository_root, name)
    records = population.load_all_records(repository_root)
    tier = {key.split(".")[0]: value.tier for key, value in records.items()}
    summary, failures = placement.check_addon_placement(
        read_cds_block(built, lo, width), lambda acc: tier.get(acc, "backbone"), name
    )
    assert not failures, failures
    assert summary["badly_placed_share"] <= CORPUS_BADLY_PLACED_CEILING
    assert summary["median_occupancy"] == 1.0


# --- the private-column ceiling ------------------------------------------------------------------
#
# Largest owner per artifact after the ambiguity filter. Pinned as a *table* rather than one
# worst-case number so a single artifact regressing cannot hide behind the others being fine.
#
# Re-measured 2026-08-18 on the artifacts the six indel repairs produced. The three numbers this
# replaces were measured on 5.0.0 and were never true of the promoted build: the gate had been
# reading them through hardcoded CDS block offsets that went stale the first time a rebuild changed
# a block width, so it was slicing the 3'NCR and measuring privateness over the wrong columns. See
# `cds_block_bounds` above. Measured honestly, the promoted build was at EV 72, NPEV 216 and POLIO
# 462, not 96/66/27.
#
# `POLIO_unified` 462 -> 15 is `OR538737` leaving: one amplicon that is half 5'UTR held the first
# 462 columns of that CDS open by itself until `segment._boundary_cut` sent its 5' half to the
# 5'NCR block. `EV_unified` 72 -> 39 is `OM885400`, the same repair's second and only other record.
#
# `NPEV_unified` stays at 216, and that is deliberate. `OR538735` carries two internal frameshifts —
# frame +1 reads as protein at 0.68-0.84 exactly where its declared frame reads 0.00-0.08 — so it is
# a bad deposit rather than a bad placement, and neither repair touches it: it is not a
# boundary-crossing amplicon, and its private block is contiguous with its own body rather than
# flung away from it. Nor is it gateable. 24 records show the same frameshift pattern, their shares
# spread continuously from 0.015 to 0.50 with no empty interval anywhere in it, and ten of them have
# a *higher* shifted share than `OR538735` while placing perfectly well. Any threshold that caught
# this one would sweep in the other twenty-three on a tuned number, which is the thing every other
# threshold in this pipeline was chosen to avoid. So it is recorded here and left alone.
LARGEST_PRIVATE_OWNER = {"EV_unified": 39, "NPEV_unified": 216, "POLIO_unified": 15}


def test_one_record_hogging_columns_is_refused() -> None:
    """The `PX242045` shape, in miniature: one row alone in a wide block of its own columns."""
    block = {f"r{i}": "ACGT" * 4 + "-" * 40 for i in range(20)}
    block["hog"] = "-" * 16 + "A" * 40
    owners, failures = placement.check_private_columns(block, "probe", ceiling=10)
    assert owners["hog"] == 40
    assert failures and "holding a block open" in failures[0]


def test_an_ordinary_insertion_is_not_refused() -> None:
    """Negative control. A ceiling that fired on every insertion would just be a width limit."""
    block = {f"r{i}": "ACGT" * 4 + "-" * 6 for i in range(20)}
    block["small"] = "ACGT" * 4 + "ACGTAG"
    owners, failures = placement.check_private_columns(block, "probe", ceiling=10)
    assert owners["small"] == 6
    assert not failures


def test_a_column_two_records_share_is_not_private() -> None:
    """Privateness is the whole predicate: two occupants means somebody agreed it is homologous."""
    block = {"a": "ACGTAA", "b": "ACGTAA", "c": "ACGT--"}
    assert placement.private_column_owners(block) == {}


@pytest.mark.slow
@pytest.mark.parametrize("name", sorted(CDS_BLOCK_NAMES))
def test_no_record_holds_a_shipped_block_open_by_itself(
    repository_root: Path, name: str
) -> None:
    built = repository_root / "final/alignments" / f"{name}_aln.fasta.gz"
    if not built.is_file():
        pytest.skip(f"{name} not promoted yet")
    lo, width = cds_block_bounds(repository_root, name)
    owners, failures = placement.check_private_columns(read_cds_block(built, lo, width), name)
    assert not failures, failures
    assert max(owners.values()) == LARGEST_PRIVATE_OWNER[name]


def test_the_declared_exemption_suppresses_the_failure_and_not_the_measurement() -> None:
    """`OR538735` is over the ceiling and stays over it. Exempting it must not make it invisible:
    the pinned table is what keeps it justified, and that table reads `owners`."""
    block = {f"r{i}": "ACGT" * 4 + "-" * 400 for i in range(20)}
    block["OR538735"] = "-" * 16 + "A" * 400
    owners, failures = placement.check_private_columns(block, "probe")
    assert owners["OR538735"] == 400
    assert not failures


def test_the_exemption_is_by_name_and_covers_nobody_else() -> None:
    """A ceiling that could be silenced by any record would not be a ceiling."""
    block = {f"r{i}": "ACGT" * 4 + "-" * 400 for i in range(20)}
    block["SOMEONE_ELSE"] = "-" * 16 + "A" * 400
    _owners, failures = placement.check_private_columns(block, "probe")
    assert failures and "holding a block open" in failures[0]
    assert "OR538735" not in placement.PRIVATE_COLUMN_EXEMPTIONS.get("SOMEONE_ELSE", "")
