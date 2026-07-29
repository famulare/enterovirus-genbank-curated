"""Alignment loading and the mapping from genome regions to alignment columns.

Two coordinate frames exist and they are not interchangeable.

`sabin` — `PV{1,2,3}_unified.sto.gz` carry a hand-built RF line whose alphabetic
columns are exactly that serotype's Sabin genome coordinates. Verified: PV1 has
7,441 such columns and projecting AY184219 onto them returns a fully ungapped
Sabin 1 genome. `reference_region_coordinates.tsv` therefore applies directly,
with no inference.

`projected` — `EV_unified.sto.gz` has a consensus RF that is explicitly *not*
comparable to the Sabin frame, and ships no region coordinates. But it contains
AY184219 and its CDS block is a clean codon MSA starting at ATG, so the P1/P2/P3
cleavage boundaries are projected from Sabin 1 through the alignment. Cleavage
sites are homologous across the genus, which is what makes this legitimate for
non-polio rows.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass

import numpy as np

import contract

# Normalized alignment encoding. Three states, and the distinction between the
# outer two is load-bearing:
#
#   0        GAP        no material here at all
#   1-4      A C G T    an unambiguous base
#   5        AMBIGUOUS  material is present but unreadable (N and the IUPAC set)
#
# Collapsing AMBIGUOUS into GAP would make an `N` look like a one-base deletion,
# which would score a non-synonymous difference and raise a frameshift flag on a
# sequence that has neither. U folds onto T because the NCR blocks use RNA notation
# where the CDS block uses DNA.
GAP = 0
NOT_COVERED = GAP  # retained name for coverage-style comparisons
AMBIGUOUS = 5

CODE = {"A": 1, "C": 2, "G": 3, "T": 4, "U": 4}
GAP_CHARACTERS = "-.~"
# Every IUPAC ambiguity code. None of them collide with ACGTU.
AMBIGUITY_CHARACTERS = "NRYSWKMBDHV"

_LOOKUP = np.zeros(256, dtype=np.uint8)
_KNOWN = np.zeros(256, dtype=bool)
for _char, _code in CODE.items():
    for _variant in (_char, _char.lower()):
        _LOOKUP[ord(_variant)] = _code
        _KNOWN[ord(_variant)] = True
for _char in AMBIGUITY_CHARACTERS:
    for _variant in (_char, _char.lower()):
        _LOOKUP[ord(_variant)] = AMBIGUOUS
        _KNOWN[ord(_variant)] = True
for _char in GAP_CHARACTERS:
    _LOOKUP[ord(_char)] = GAP
    _KNOWN[ord(_char)] = True


def is_base(block: np.ndarray) -> np.ndarray:
    """True where an unambiguous nucleotide is present. The comparability test."""
    return (block >= 1) & (block <= 4)


def has_material(block: np.ndarray) -> np.ndarray:
    """True where the sequence has something, readable or not. The indel test."""
    return block != GAP


@dataclass
class Alignment:
    name: str
    ids: list[str]
    index: dict[str, int]
    matrix: np.ndarray  # (n_rows, width) uint8, normalized
    rf: str
    provenance: dict

    @property
    def width(self) -> int:
        return int(self.matrix.shape[1])

    def row(self, accession: str) -> np.ndarray:
        return self.matrix[self.index[accession]]


def read_stockholm(path) -> tuple[dict[str, str], dict[str, str]]:
    """Return (sequence rows, #=GC annotation lines), concatenating any blocks."""
    seqs: dict[str, list[str]] = {}
    order: list[str] = []
    gc: dict[str, list[str]] = {}
    with gzip.open(path, "rt") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line == "//":
                continue
            if line.startswith("#=GC"):
                parts = line.split(None, 2)
                if len(parts) == 3:
                    gc.setdefault(parts[1], []).append(parts[2])
                continue
            if line.startswith("#"):
                continue
            parts = line.split(None, 1)
            if len(parts) != 2:
                continue
            name, chunk = parts
            if name not in seqs:
                seqs[name] = []
                order.append(name)
            seqs[name].append(chunk)
    return (
        {name: "".join(seqs[name]) for name in order},
        {key: "".join(chunks) for key, chunks in gc.items()},
    )


def load_alignment(name: str) -> Alignment:
    rows, gc = read_stockholm(contract.alignment_sto(name))
    ids = list(rows)
    widths = {len(seq) for seq in rows.values()}
    if len(widths) != 1:
        raise ValueError(f"{name}: ragged alignment, widths {sorted(widths)}")
    width = widths.pop()

    raw = np.frombuffer("".join(rows[i] for i in ids).encode("ascii"), dtype=np.uint8)
    # An unrecognized character would fall through to GAP and could then be
    # miscounted as an indel, so refuse to guess.
    unknown = np.unique(raw[~_KNOWN[raw]])
    if len(unknown):
        raise ValueError(
            f"{name}: unrecognized alignment characters "
            f"{[chr(c) for c in unknown]}. Add them to frame.CODE, "
            "AMBIGUITY_CHARACTERS or GAP_CHARACTERS with an explicit meaning."
        )
    matrix = _LOOKUP[raw].reshape(len(ids), width)

    rf = gc.get("RF", "")
    if rf and len(rf) != width:
        raise ValueError(f"{name}: RF length {len(rf)} != alignment width {width}")

    provenance_path = contract.alignment_provenance(name)
    provenance = json.loads(provenance_path.read_text()) if provenance_path.exists() else {}

    return Alignment(
        name=name,
        ids=ids,
        index={acc: i for i, acc in enumerate(ids)},
        matrix=matrix,
        rf=rf,
        provenance=provenance,
    )


def read_region_coordinates() -> dict[str, dict[str, tuple[int, int]]]:
    """serotype -> region name -> (start, end), 1-based inclusive, Sabin coordinates."""
    out: dict[str, dict[str, tuple[int, int]]] = {}
    with open(contract.REGION_COORDINATES) as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            out.setdefault(row["serotype"], {})[row["region"]] = (
                int(row["start"]),
                int(row["end"]),
            )
    return out


def _cds_offsets(coords: dict[str, tuple[int, int]]) -> dict[str, tuple[int, int]]:
    """Region spans as 1-based nucleotide offsets into the polyprotein CDS."""
    cds_start = coords[contract.P1_GENES[0]][0]
    p2_start = coords[contract.P2_GENES[0]][0]
    p3_start = coords[contract.P3_GENES[0]][0]
    cds_end = coords[contract.P3_GENES[-1]][1]
    return {
        contract.REGION_P1: (1, p2_start - cds_start),
        contract.REGION_P2: (p2_start - cds_start + 1, p3_start - cds_start),
        contract.REGION_P3: (p3_start - cds_start + 1, cds_end - cds_start + 1),
        contract.REGION_POLYPROTEIN: (1, cds_end - cds_start + 1),
    }


# --- Sabin frame -----------------------------------------------------------


def sabin_region_columns(
    alignment: Alignment, serotype: str, coords: dict[str, dict[str, tuple[int, int]]]
) -> dict[str, np.ndarray]:
    """Region -> alignment column indices, via the hand-built RF line.

    The RF line's alphabetic columns enumerate Sabin coordinates 1..N in order, so
    Sabin position p is alignment column `match[p - 1]`.
    """
    match = np.array([i for i, char in enumerate(alignment.rf) if char.isalpha()], dtype=np.int64)
    region = coords[serotype]
    expected = region["3UTR"][1]
    if len(match) != expected:
        raise ValueError(
            f"{alignment.name}: {len(match)} RF match columns but the coordinate table "
            f"ends at {expected}. The Sabin frame assumption is broken."
        )

    def span(start: int, end: int) -> np.ndarray:
        return match[start - 1 : end]

    out = {
        contract.REGION_5NCR: span(*region["5UTR"]),
        contract.REGION_3NCR: span(*region["3UTR"]),
    }
    cds_start = region[contract.P1_GENES[0]][0]
    for name, (lo, hi) in _cds_offsets(region).items():
        out[name] = span(cds_start + lo - 1, cds_start + hi - 1)
    return out


# --- Projected frame -------------------------------------------------------


def _blocks(alignment: Alignment) -> tuple[int, int, int]:
    widths = alignment.provenance.get("block_widths")
    if not widths:
        raise ValueError(f"{alignment.name}: provenance declares no block_widths")
    five, cds, three = widths["5ncr"], widths["cds"], widths["3ncr"]
    if five + cds + three != alignment.width:
        raise ValueError(
            f"{alignment.name}: blocks {five}+{cds}+{three} != width {alignment.width}"
        )
    return five, cds, three


def projected_region_columns(
    alignment: Alignment, coords: dict[str, dict[str, tuple[int, int]]]
) -> dict[str, np.ndarray]:
    """Region -> alignment column indices, by projecting Sabin 1 cleavage sites.

    Regions are contiguous column ranges rather than the anchor's own non-gap
    columns, so insertion columns carried by non-polio rows are kept. Boundaries
    land on codon starts, which is asserted rather than assumed.
    """
    five, cds_width, _three = _blocks(alignment)
    cds_lo, cds_hi = five, five + cds_width

    anchor = alignment.row(contract.PROJECTION_ANCHOR)
    covered = np.nonzero(anchor[cds_lo:cds_hi] != NOT_COVERED)[0] + cds_lo
    if len(covered) % 3:
        raise ValueError(
            f"{alignment.name}: anchor CDS is {len(covered)} nt, not a whole number of codons"
        )

    offsets = _cds_offsets(coords[contract.PROJECTION_ANCHOR_SEROTYPE])

    def boundary(nt_offset: int) -> int:
        """Alignment column holding the anchor's CDS nucleotide `nt_offset` (1-based)."""
        return int(covered[min(nt_offset, len(covered)) - 1])

    p2_lo = boundary(offsets[contract.REGION_P2][0])
    p3_lo = boundary(offsets[contract.REGION_P3][0])
    for label, column in (("P2", p2_lo), ("P3", p3_lo)):
        if (column - cds_lo) % 3:
            raise ValueError(
                f"{alignment.name}: projected {label} boundary at column {column} is out of "
                f"codon phase with the CDS block start {cds_lo}"
            )

    out = {
        contract.REGION_5NCR: np.arange(0, five, dtype=np.int64),
        contract.REGION_3NCR: np.arange(cds_hi, alignment.width, dtype=np.int64),
        contract.REGION_P1: np.arange(cds_lo, p2_lo, dtype=np.int64),
        contract.REGION_P2: np.arange(p2_lo, p3_lo, dtype=np.int64),
        contract.REGION_P3: np.arange(p3_lo, cds_hi, dtype=np.int64),
        contract.REGION_POLYPROTEIN: np.arange(cds_lo, cds_hi, dtype=np.int64),
    }

    # Cross-check the projection against the independent Sabin-frame widths: the
    # anchor's own non-gap count inside each projected region must equal that
    # region's per-serotype width. P1 and P2 only — P3 and the whole polyprotein
    # are short by one codon, because the CDS block excludes the stop.
    for name in (contract.REGION_P1, contract.REGION_P2):
        lo, hi = offsets[name]
        found = int((anchor[out[name]] != NOT_COVERED).sum())
        if found != hi - lo + 1:
            raise ValueError(
                f"{alignment.name}: projected {name} holds {found} anchor nt, "
                f"expected {hi - lo + 1}"
            )
    return out


def region_columns(
    alignment: Alignment, selection: dict, coords: dict[str, dict[str, tuple[int, int]]]
) -> dict[str, np.ndarray]:
    if selection["frame"] == "sabin":
        return sabin_region_columns(alignment, selection["id"], coords)
    return projected_region_columns(alignment, coords)


# --- Coverage --------------------------------------------------------------


def coverage(alignment: Alignment, columns: np.ndarray) -> np.ndarray:
    """Unambiguous nucleotides per row within `columns`."""
    return is_base(alignment.matrix[:, columns]).sum(axis=1, dtype=np.int32)


# --- Translation -----------------------------------------------------------

_BASES = "TCAG"
_AMINO = (
    "FFLLSSSSYY**CC*W"
    "LLLLPPPPHHQQRRRR"
    "IIIMTTTTNNKKSSRR"
    "VVVVAAAADDEEGGGG"
)
# Normalized code -> its offset in the TCAG ordering the standard codon table is
# written in. GAP and AMBIGUOUS both map to 0 so that a non-comparable codon still
# produces an in-range lookup; callers must mask those out by comparability, and
# never trust the amino acid returned for one. Sized to cover every code including
# AMBIGUOUS.
_CODE_TO_TCAG = np.zeros(AMBIGUOUS + 1, dtype=np.uint8)
for _char, _code in (("T", 4), ("C", 2), ("A", 1), ("G", 3)):
    _CODE_TO_TCAG[_code] = _BASES.index(_char)

CODON_TABLE = np.frombuffer(_AMINO.encode("ascii"), dtype=np.uint8)


def translate(codons: np.ndarray) -> np.ndarray:
    """(..., 3) of normalized codes -> (...) of amino-acid bytes.

    Uncovered positions yield a meaningless-but-in-range result rather than an
    error, because the caller already knows which codons are comparable and masking
    afterwards is far cheaper than masking three arrays beforehand.
    """
    tcag = _CODE_TO_TCAG[codons].astype(np.int32)
    return CODON_TABLE[(tcag[..., 0] * 4 + tcag[..., 1]) * 4 + tcag[..., 2]]


def as_codons(block: np.ndarray) -> np.ndarray:
    """(n, L) -> (n, L/3, 3). L must already be a whole number of codons."""
    if block.shape[-1] % 3:
        raise ValueError(f"{block.shape[-1]} columns is not a whole number of codons")
    return block.reshape(*block.shape[:-1], block.shape[-1] // 3, 3)


# --- Run-length analysis over a boolean mask -------------------------------


def run_stats(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per-row count of maximal True runs, and whether any run length is not a
    multiple of three.

    Vectorized by padding each row with False and flattening, so runs cannot merge
    across the row boundary and every run can be located with one flatnonzero.
    """
    rows, width = mask.shape
    padded = np.zeros((rows, width + 2), dtype=bool)
    padded[:, 1:-1] = mask
    flat = padded.reshape(-1)

    starts = np.flatnonzero(flat[1:] & ~flat[:-1]) + 1
    ends = np.flatnonzero(flat[:-1] & ~flat[1:])
    lengths = ends - starts + 1
    row_of_run = starts // (width + 2)

    counts = np.bincount(row_of_run, minlength=rows).astype(np.int32)
    shifting = np.bincount(row_of_run, weights=(lengths % 3 != 0), minlength=rows)
    return counts, shifting > 0
