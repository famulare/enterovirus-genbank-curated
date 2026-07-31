"""Assemble the 5'NCR + CDS + 3'NCR blocks into one row per record.

Ported from MAD-VDPV's `build_{ev,polio,grand_ev}_unified_stockholm.py` and, for the anchored
stack, `build_unified_stockholm.py` — upstream had one of these per population; the assembly is the
same in all of them. `#=GC RF` is computed per block: a per-column majority nucleotide for the
unified stack, or the reference's own bases where the caller supplies `cds_rf` (see `stitch`).
`#=GC SS_cons` carries each NCR block's own consensus structure with an all-gap run over the CDS
span (protein-coding, no base-pair model). Row order is this repo's own already-declared convention
(`align.population.select`'s `(type_sort_key, accession)`), not upstream's `(family, virus_type,
accession)` — a population's `.records` order is already that, so this module just follows it.

Every record in the population gets exactly one row at the full stitched width, even one whose
segmentation placed nothing at all (`method == "none"`) — the whole point of a population-derived
design is that the row set is 1-to-1 with metadata, and a missing row would silently break that. A
record missing a given block is padded with an all-gap span of that block's width. Which block(s)
were missing, and why, is recorded per record in the returned coverage rows: an absent block is
distinguishable from a genuine deletion via that table, never by inventing a new alignment
character.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Protocol

from enterovirus_genbank_curated.align import contract, structural
from enterovirus_genbank_curated.align.population import AlignedRecord, AlignmentPopulation
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.align.structural import NcrBlock
from enterovirus_genbank_curated.contracts import ContractError


class CdsBlock(Protocol):
    """All this module needs of a CDS block, whichever stack produced it.

    Stated as a protocol rather than a union of `codon.CodonAlignment` and
    `anchored.AnchoredCdsBlock` because stitching genuinely does not depend on which one it got —
    a fixed width and one row per placed record is the entire contract. The two differ in what
    `#=GC RF` means over that span, and that is passed separately as `cds_rf`.
    """

    width_nt: int
    aligned_nt: dict[str, str]


GAP = "-"
GAP_RF = "."

BLOCK_5NCR = "5ncr"
BLOCK_CDS = "cds"
BLOCK_3NCR = "3ncr"
BLOCKS = (BLOCK_5NCR, BLOCK_CDS, BLOCK_3NCR)

# A record whose segmentation succeeded via inference has no NCR at all by design — not a
# failure, and not one of align.segment's own ABSENCE_* reasons (those are for method == "none").
REASON_INFERRED_NO_NCR = "inferred_no_ncr"


@dataclass(frozen=True)
class CoverageRow:
    accession: str
    version: str
    tier: str
    family: str
    virus_type: str
    block: str
    present: bool
    source_nt: int
    block_nt: int
    absence_reason: str | None


@dataclass(frozen=True)
class StitchedAlignment:
    accessions: tuple[str, ...]
    width_5ncr: int
    width_cds: int
    width_3ncr: int
    width_nt: int
    aligned_nt: dict[str, str]
    rf: str
    ss_cons: str
    coverage: tuple[CoverageRow, ...]


def _majority_rf(rows: list[str], width: int) -> str:
    """Per-column majority nucleotide over non-gap characters; `.` if every row is a gap there.
    `rows` must be supplied in a deterministic order — the tie-break among equally-common
    characters is "whichever appeared first", exactly as `Counter.most_common` behaves."""
    columns = []
    for i in range(width):
        counts = Counter(row[i] for row in rows if row[i] != GAP)
        columns.append(counts.most_common(1)[0][0] if counts else GAP_RF)
    return "".join(columns)


def _ncr_absence_reason(
    segmentation: Segmentation, side: str, side_spec: contract.NcrSideSpec
) -> str:
    if segmentation.method == "none":
        assert segmentation.absence_reason is not None
        return segmentation.absence_reason
    if segmentation.method == "inferred":
        return REASON_INFERRED_NO_NCR
    fragment = segmentation.ncr5 if side == "5p" else segmentation.ncr3
    classification = structural.classify_fragment(fragment, side_spec)
    if classification == structural.FRAGMENT_INCLUDED:
        raise ContractError(
            f"{segmentation.accession}: {side} fragment classifies as included, but the record "
            f"has no row in this side's NcrBlock — the block and the classifier disagree"
        )
    return classification


def _coverage_row(
    record: AlignedRecord, block: str, row: str | None, width: int, source_nt: int,
    absence_reason: str | None,
) -> CoverageRow:
    present = row is not None
    return CoverageRow(
        accession=record.accession,
        version=record.version,
        tier=record.tier,
        family=record.family,
        virus_type=record.type_sort_key,
        block=block,
        present=present,
        source_nt=source_nt,
        block_nt=width,
        absence_reason=None if present else absence_reason,
    )


def stitch(
    population: AlignmentPopulation,
    segmentations: dict[str, Segmentation],
    cds_block: CdsBlock,
    five_prime: NcrBlock,
    three_prime: NcrBlock,
    *,
    cds_rf: str | None = None,
) -> StitchedAlignment:
    """Assemble one row per population record.

    `cds_rf` overrides the CDS span's `#=GC RF`. The unified stack leaves it None and gets a
    per-column majority nucleotide, which is the only honest summary of a de-novo profile alignment.
    The anchored stack passes the Sabin reference's own CDS substring, because there every column
    *is* that reference's position and a majority would obscure a coordinate the reader can use.
    """
    ncr_spec = population.spec.ncr
    if ncr_spec is None:
        raise ContractError(f"{population.spec.name} has no declared NcrSpec")
    if five_prime.side != "5p" or three_prime.side != "3p":
        raise ContractError(
            f"expected a 5p and a 3p NcrBlock, got {five_prime.side!r} and {three_prime.side!r}"
        )

    width_5 = five_prime.width_nt
    width_cds = cds_block.width_nt
    width_3 = three_prime.width_nt
    total_width = width_5 + width_cds + width_3

    aligned_nt: dict[str, str] = {}
    coverage: list[CoverageRow] = []
    accessions = tuple(record.accession for record in population.records)

    for record in population.records:
        segmentation = segmentations[record.accession]

        row5 = five_prime.aligned_nt.get(record.accession)
        row_cds = cds_block.aligned_nt.get(record.accession)
        row3 = three_prime.aligned_nt.get(record.accession)

        stitched = (
            (row5 if row5 is not None else GAP * width_5)
            + (row_cds if row_cds is not None else GAP * width_cds)
            + (row3 if row3 is not None else GAP * width_3)
        )
        if len(stitched) != total_width:
            raise ContractError(
                f"{record.accession}: stitched width {len(stitched)} != {total_width}"
            )
        aligned_nt[record.accession] = stitched

        reason_5 = None if row5 is not None else _ncr_absence_reason(
            segmentation, "5p", ncr_spec.five_prime
        )
        reason_3 = None if row3 is not None else _ncr_absence_reason(
            segmentation, "3p", ncr_spec.three_prime
        )
        coverage.append(
            _coverage_row(record, BLOCK_5NCR, row5, width_5, len(segmentation.ncr5), reason_5)
        )
        coverage.append(
            _coverage_row(
                record, BLOCK_CDS, row_cds, width_cds, len(segmentation.orf_nt),
                None if row_cds is not None else segmentation.absence_reason,
            )
        )
        coverage.append(
            _coverage_row(record, BLOCK_3NCR, row3, width_3, len(segmentation.ncr3), reason_3)
        )

    ordered_accessions_5 = [a for a in accessions if a in five_prime.aligned_nt]
    ordered_accessions_3 = [a for a in accessions if a in three_prime.aligned_nt]
    ordered_accessions_cds = [a for a in accessions if a in cds_block.aligned_nt]

    rows_5 = [five_prime.aligned_nt[a] for a in ordered_accessions_5]
    rows_3 = [three_prime.aligned_nt[a] for a in ordered_accessions_3]
    rows_cds = [cds_block.aligned_nt[a] for a in ordered_accessions_cds]
    rf5 = _majority_rf(rows_5, width_5) if width_5 else ""
    rf3 = _majority_rf(rows_3, width_3) if width_3 else ""
    rf_cds = cds_rf if cds_rf is not None else _majority_rf(rows_cds, width_cds)
    rf = rf5 + rf_cds + rf3
    ss_cons = five_prime.ss_cons + (GAP_RF * width_cds) + three_prime.ss_cons

    return StitchedAlignment(
        accessions=accessions,
        width_5ncr=width_5,
        width_cds=width_cds,
        width_3ncr=width_3,
        width_nt=total_width,
        aligned_nt=aligned_nt,
        rf=rf,
        ss_cons=ss_cons,
        coverage=tuple(coverage),
    )
