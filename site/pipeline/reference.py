"""What each sequence is measured against.

Poliovirus has a vaccine reference, so a polio record is compared to the Sabin
genome of its serotype. Non-polio enterovirus has none, so it is compared to a
consensus of its own virus type — which makes an outlier read as a candidate
misclassification rather than merely as a divergent virus.

**There is deliberately no species or genus fallback.** An earlier version stepped
outward — virus type, then species, then genus — when a type had too few sequences
to support a consensus. That was a conceptual error, not a tuning problem:

  - An enterovirus species holds dozens of serotypes that are 25-30% divergent
    across the capsid, so a per-column majority over all of them is a chimera. At
    every position where the types disagree the consensus base is close to
    arbitrary.
  - The resulting number is not commensurable with the type-consensus and Sabin
    numbers on the same axis. It folds "how unusual is this type within its species"
    into "how far has this sequence drifted within its type" — two different
    quantities sharing one axis, which is exactly the comparison the figure exists
    to support.

So a record whose own virus type cannot support a consensus has no comparable
reference, and is reported as unmeasurable rather than given a fake one. It is
excluded from this figure only; the distance and phylogeny views need no reference
and keep it.

A type qualifies with at least MIN_CONSENSUS_ROWS contributing sequences, where a
contributor carries at least MIN_CONSENSUS_NT nucleotides in the region being
measured. Consensus is computed per region rather than genome-wide: most of the
alignment is gap for most records, so a whole-genome consensus would be dominated
by whichever subset happens to be complete.

Caveat that remains, and is surfaced per record: a consensus from few contributors
is defined largely *by* those contributors, so they sit artificially close to it. A
type's contributor count therefore travels with its reference label.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import contract
import frame

# Reference kinds, surfaced in the artifact so a tooltip can say what a dot was
# measured against rather than leaving the reader to assume.
KIND_SABIN = "sabin"
KIND_TYPE = "type_consensus"
KIND_NONE = "none"


@dataclass
class References:
    """Distinct reference sequences, plus which one each row uses.

    `sequences` is (n_references, region_width) of normalized codes; `row_index`
    maps each row of the selection to a row of `sequences`, or -1 when no reference
    could be resolved.
    """

    sequences: np.ndarray
    row_index: np.ndarray
    kinds: list[str]
    labels: list[str]

    def unresolved(self) -> int:
        return int((self.row_index < 0).sum())


def _consensus(block: np.ndarray, contributors: np.ndarray) -> np.ndarray:
    """Per-column majority nucleotide over `contributors`, 0 where all are gaps.

    KNOWN LIMITATION, confirmed and deliberately left in place. A column carries a
    base whenever ANY contributor has one, so a consensus over many mixed-length rows
    is a *union* of their coverage rather than a typical sequence of the type. An
    individual record then reads as deleted at every column it does not span but some
    same-type record does, which inflates its indel-codon count — and therefore its
    non-synonymous rate — in proportion to how fragmentary its type is.

    Measured on release 2.1.5 and re-verified unchanged at 2.4.1 (this artifact's inputs — the
    NPEV_unified alignment and the underlying sequences — have not moved across any refresh so
    far): 487 of 13,161 non-polio polyprotein records exceed 0.5 non-synonymous per codon, and
    indel codons are 80.5% of that group's numerator. They concentrate in the largest, most
    fragmentary types — CVA24 238, CVA13 81.

    Not fixed here. The consensus is a stand-in for reference sequences the release
    does not yet carry for non-polio types; the fix is an upstream per-type reference,
    not a quorum rule bolted onto a stand-in. Until then the artifact is disclosed
    where the figure is, and in site/README.md, rather than silently smoothed.
    """
    counts = np.zeros((4, block.shape[1]), dtype=np.int32)
    rows = block[contributors]
    for code in range(1, 5):
        counts[code - 1] = (rows == code).sum(axis=0)
    best = counts.argmax(axis=0).astype(np.uint8) + 1
    # A column where no contributor has an unambiguous base becomes a gap, so it is
    # neither comparable nor a source of spurious indels.
    return np.where(counts.max(axis=0) > 0, best, frame.GAP).astype(np.uint8)


def _group_keys(records: list[dict], group: str) -> list[str]:
    if group == "type":
        return [record["virus_type"] or "" for record in records]
    raise ValueError(group)


def resolve(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: np.ndarray,
    selection: dict,
    records_by_row: list[dict],
    region: str,
) -> References:
    """Build the reference set for one selection and one region."""
    block = alignment.matrix[np.ix_(rows, columns)]
    eligible = frame.is_base(block).sum(axis=1) >= contract.MIN_CONSENSUS_NT

    sequences: list[np.ndarray] = []
    kinds: list[str] = []
    labels: list[str] = []
    row_index = np.full(len(rows), -1, dtype=np.int32)

    def add(sequence: np.ndarray, kind: str, label: str) -> int:
        sequences.append(sequence)
        kinds.append(kind)
        labels.append(label)
        return len(sequences) - 1

    # Sabin, for whichever serotypes are present in this alignment.
    sabin_slot: dict[str, int] = {}
    for serotype, accession in contract.SABIN_REFERENCE.items():
        if accession in alignment.index:
            sabin_slot[serotype] = add(
                alignment.matrix[alignment.index[accession], columns],
                KIND_SABIN,
                f"Sabin {serotype[-1]} ({accession})",
            )

    # A per-serotype selection measures every row against that serotype's Sabin,
    # including rows whose curated type disagrees — a sequence sitting far from the
    # Sabin its alignment placed it against is exactly the signal worth seeing.
    if selection["id"] in contract.SABIN_REFERENCE:
        slot = sabin_slot.get(selection["id"])
        if slot is None:
            raise ValueError(
                f"{alignment.name} carries no Sabin row for {selection['id']}"
            )
        row_index[:] = slot
        return References(np.array(sequences), row_index, kinds, labels)

    # Mixed selections: polio rows take their serotype's Sabin, the rest a consensus.
    types = _group_keys(records_by_row, "type")
    for position, virus_type in enumerate(types):
        if virus_type in sabin_slot:
            row_index[position] = sabin_slot[virus_type]

    pending = np.flatnonzero(row_index < 0)
    if not len(pending):
        return References(np.array(sequences), row_index, kinds, labels)

    # Virus type, and only virus type. See the module docstring for why there is no
    # species or genus rung.
    types = _group_keys(records_by_row, "type")
    buckets: dict[str, list[int]] = {}
    for position in pending:
        key = types[position]
        if key:
            buckets.setdefault(key, []).append(int(position))

    for key, members in buckets.items():
        contributors = np.array([p for p in members if eligible[p]], dtype=np.int64)
        if len(contributors) < contract.MIN_CONSENSUS_ROWS:
            continue
        slot = add(
            _consensus(block, contributors),
            KIND_TYPE,
            f"{key} consensus of {len(contributors)}",
        )
        row_index[np.array(members, dtype=np.int64)] = slot

    return References(np.array(sequences), row_index, kinds, labels)
