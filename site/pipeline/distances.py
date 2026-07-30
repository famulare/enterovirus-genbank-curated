"""Masked pairwise nucleotide distance, and the landmark set an embedding needs.

Distance between two sequences is mismatches divided by the alignment columns where
**both** carry an unambiguous base. Nothing is imputed and no substitution model is
applied: this is the same uncorrected currency as figure set 1, in nucleotide space
rather than codon space, which is why it needs no reading frame and can therefore
cover the two non-coding regions.

The hard part is not the arithmetic, it is that **a pair can share no columns at
all.** A 5'NCR fragment and a 3D fragment overlap nowhere, so their distance does not
exist — it is not large, it is undefined. Genus-wide, 11% of P1 pairs share fewer
than 50 columns. An embedding needs a complete matrix, so the design is:

  - pick a **landmark** set of densely-covered sequences whose pairwise distances are
    *all* defined, and embed those exactly;
  - place every other sequence by its distances to the landmarks it does overlap,
    and record how many that was, so the figure can draw a thinly-placed point
    differently from a confidently-placed one.

That keeps every sequence on screen without pretending a fragment's position is as
trustworthy as a whole genome's.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

import frame

# Landmarks are embedded exactly, so this caps an O(L^2) eigendecomposition and an
# O(n L) projection. 1,500 is far more than two dimensions can use, and keeps the
# largest panel's landmark block inside a few hundred megabytes.
LANDMARK_CAP = 1500

# Rows processed at once when projecting against the landmarks. Each chunk holds one
# float32 plane of (chunk x columns), so this bounds peak memory independent of n.
CHUNK = 6000

# How many rows the mutual-comparability greedy considers, best-covered first. The
# greedy needs a pool x pool overlap matrix, so this bounds it at 6,000^2 float32 =
# 144 MB. Every figure draws its set from this one pool, using the same ordering, so
# a smaller cap always yields a prefix of what a larger cap yields.
CANDIDATE_POOL = 6000


@dataclass(frozen=True)
class Alphabet:
    """What counts as readable material, and which codes a match is counted over.

    The metric is identical in nucleotide and residue space — mismatches over the
    positions where both sequences carry readable material, pairwise, with a length
    minimum — so it is written once and parameterized rather than written twice.
    """

    name: str
    unit: str
    readable: Callable[[np.ndarray], np.ndarray]
    codes: tuple[int, ...]


NUCLEOTIDE = Alphabet("nucleotide", "nt", frame.is_base, tuple(range(1, 5)))
RESIDUE = Alphabet(
    "residue", "codons", frame.is_residue, tuple(range(1, len(frame.RESIDUE_SYMBOLS) + 1))
)


def in_alphabet(
    block: np.ndarray, min_nt: int, columns: int, alphabet: Alphabet
) -> tuple[np.ndarray, int, int]:
    """A nucleotide block, floor and width, restated in the alphabet's own unit.

    Every protein figure goes through here, so they cannot end up disagreeing about what
    the floor means. The floor rounds UP, which is the part that bites: 50 nt is 16.7
    codons, and rounding down to 16 makes the protein floor 48 nt — looser than the
    nucleotide floor it is meant to restate, which let one record onto a protein figure
    while being absent from every nucleotide one. At 17 codons the floor is 51 nt, so a
    record in a protein figure is always in the nucleotide figures too.
    """
    if alphabet is NUCLEOTIDE:
        return block, min_nt, columns
    return frame.residue_block(block), max(1, -(-min_nt // 3)), columns // 3

# A row needs at least this fraction of the landmarks resolved before its position is
# treated as confident. Below it the point is drawn open.
CONFIDENT_LANDMARK_FRACTION = 0.9

# ... and this much overlap on the landmarks it does resolve, as a fraction of the
# region's own width, capped so a whole genome is not held to an absurd standard.
#
# Region-relative, not absolute: an earlier fixed floor of 200 columns exceeded the
# entire width of the 3'NCR block (87 columns), so every 3'NCR point was marked thin
# and the encoding said nothing at all. "Confident" has to mean substantial overlap
# *for this region*.
CONFIDENT_SHARED_FRACTION = 0.5
CONFIDENT_SHARED_CAP = 300


def confident_shared(columns: int) -> int:
    """The overlap a placement is expected to rest on, as a whole number of positions.

    An integer because it is a count and the figures quote it to the reader. Returning
    the raw float meant the 3'NCR's floor was 34.5, which shipped truncated to 34 while
    the comparison still used 34.5 — so a tip sharing exactly 34 positions was marked
    thin and simultaneously reported as clearing the bar.
    """
    return int(min(CONFIDENT_SHARED_CAP, CONFIDENT_SHARED_FRACTION * columns))


def counts_against(
    block: np.ndarray,
    rows: np.ndarray,
    reference_rows: np.ndarray,
    alphabet: Alphabet = NUCLEOTIDE,
) -> tuple[np.ndarray, np.ndarray]:
    """Shared positions and matching positions between `rows` and `reference_rows`.

    Returned as (shared, matches), both (len(rows), len(reference_rows)) float32.
    Counting via matrix products rather than pairwise loops is what makes a
    22,000 x 1,500 comparison over 4,887 columns take seconds instead of hours.
    """
    right = block[reference_rows]
    right_valid = alphabet.readable(right).astype(np.float32)
    shared = np.zeros((len(rows), len(reference_rows)), dtype=np.float32)
    matches = np.zeros_like(shared)

    for start in range(0, len(rows), CHUNK):
        stop = min(start + CHUNK, len(rows))
        left = block[rows[start:stop]]
        shared[start:stop] = alphabet.readable(left).astype(np.float32) @ right_valid.T
        for code in alphabet.codes:
            matches[start:stop] += (left == code).astype(np.float32) @ (
                right == code
            ).astype(np.float32).T
    return shared, matches


def shared_against(
    block: np.ndarray,
    rows: np.ndarray,
    reference_rows: np.ndarray,
    alphabet: Alphabet = NUCLEOTIDE,
) -> np.ndarray:
    """Shared positions only. One matrix product instead of one per code, which is a
    twenty-fold saving in residue space where the alphabet has twenty-one members and
    the selection step needs the overlap but not the mismatches."""
    right_valid = alphabet.readable(block[reference_rows]).astype(np.float32)
    shared = np.zeros((len(rows), len(reference_rows)), dtype=np.float32)
    for start in range(0, len(rows), CHUNK):
        stop = min(start + CHUNK, len(rows))
        left_valid = alphabet.readable(block[rows[start:stop]]).astype(np.float32)
        shared[start:stop] = left_valid @ right_valid.T
    return shared


def distance_from_counts(
    shared: np.ndarray, matches: np.ndarray, min_shared: int
) -> np.ndarray:
    """Mismatches per shared column, NaN where the pair overlaps too little.

    NaN rather than a sentinel value, so an undefined distance cannot be silently
    averaged into anything downstream.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        distance = (shared - matches) / shared
    return np.where(shared >= min_shared, distance, np.nan).astype(np.float32)


def eligible(block: np.ndarray, min_nt: int, alphabet: Alphabet = NUCLEOTIDE) -> np.ndarray:
    """Row indices carrying enough readable material to place at all."""
    return np.flatnonzero(alphabet.readable(block).sum(axis=1) >= min_nt)


def comparable_set(
    block: np.ndarray,
    rows: np.ndarray,
    min_shared: int,
    cap: int,
    required: int | None = None,
    alphabet: Alphabet = NUCLEOTIDE,
) -> np.ndarray:
    """The largest set of rows the greedy finds whose pairwise distances are ALL defined.

    Pairwise deletion with a length minimum — the same rule figure set 1 uses — leaves
    some pairs with no comparable positions at all, and those distances do not exist.
    Anything that needs a complete matrix (an eigendecomposition, a neighbor join) has
    to work on a subset where none are missing, so this finds one.

    Ordered by **overlap degree**: how many other candidates a row is comparable to at
    all. Ordering by coverage instead looked natural and was badly wrong. It admits the
    longest sequence first, and one early fragment covering only VP4 then rejects every
    VP1-only record behind it, because a VP4 fragment and a VP1 fragment share no
    columns. On PV1's P1 that kept 672 of the 3,442 attainable sequences. Degree
    ordering starts from the part of the region that everything covers — VP1, here, and
    that is not a coincidence: VP1 is the typing gene, which is why a record is in the
    alignment at all — so the mutually-comparable core is found first and the odd
    fragments are the rows that get rejected.

    `required` is admitted first whatever its degree, so a figure's reference sequence
    is always present to root or to orient it.
    """
    coverage = alphabet.readable(block[rows]).sum(axis=1)
    pool = rows[np.argsort(-coverage, kind="stable")][: min(len(rows), CANDIDATE_POOL)]
    if required is not None and required not in pool:
        pool = np.concatenate([np.array([required], dtype=pool.dtype), pool[:-1]])

    overlaps = shared_against(block, pool, pool, alphabet) >= min_shared
    # Stable, so equal-degree rows keep their coverage order and the result is
    # reproducible run to run.
    order = np.argsort(-overlaps.sum(axis=1), kind="stable")
    if required is not None:
        first = np.flatnonzero(pool == required)
        if len(first):
            order = np.concatenate([first, order[order != first[0]]])

    chosen: list[int] = []
    for index in order:
        if not chosen or bool(overlaps[index, chosen].all()):
            chosen.append(int(index))
        if len(chosen) >= cap:
            break
    return pool[np.array(chosen, dtype=np.int64)]


def complete_matrix(
    block: np.ndarray,
    members: np.ndarray,
    min_shared: int,
    alphabet: Alphabet = NUCLEOTIDE,
) -> np.ndarray:
    """Complete square distance matrix over `members`. Raises if any pair is undefined,
    because that is a bug in `comparable_set`, not a data condition."""
    shared, matches = counts_against(block, members, members, alphabet)
    distance = distance_from_counts(shared, matches, min_shared)
    np.fill_diagonal(distance, 0.0)
    if np.isnan(distance).any():
        raise ValueError(
            f"{int(np.isnan(distance).sum())} pairs in the set are undefined; "
            "comparable_set admitted a row it should have rejected"
        )
    return distance


def to_landmarks(
    block: np.ndarray,
    rows: np.ndarray,
    landmarks: np.ndarray,
    min_shared: int,
    alphabet: Alphabet = NUCLEOTIDE,
) -> tuple[np.ndarray, np.ndarray]:
    """Each row's distances to every landmark, plus its shared-column counts."""
    shared, matches = counts_against(block, rows, landmarks, alphabet)
    return distance_from_counts(shared, matches, min_shared), shared


def confidence(
    distance: np.ndarray, shared: np.ndarray, columns: int
) -> tuple[np.ndarray, np.ndarray]:
    """Per row: resolved-landmark count, and whether its placement is confident.

    Confidence is reported rather than enforced. A thinly-placed sequence still gets
    a position — it is drawn open so the reader can discount it.
    """
    resolved = (~np.isnan(distance)).sum(axis=1).astype(np.int32)
    with np.errstate(invalid="ignore"):
        median_shared = np.nanmedian(np.where(np.isnan(distance), np.nan, shared), axis=1)
    median_shared = np.nan_to_num(median_shared, nan=0.0)
    confident = (resolved >= CONFIDENT_LANDMARK_FRACTION * distance.shape[1]) & (
        median_shared >= confident_shared(columns)
    )
    return resolved, confident
