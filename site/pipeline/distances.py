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

import numpy as np

import frame

# Landmarks are embedded exactly, so this caps an O(L^2) eigendecomposition and an
# O(n L) projection. 1,500 is far more than two dimensions can use, and keeps the
# largest panel's landmark block inside a few hundred megabytes.
LANDMARK_CAP = 1500

# Rows processed at once when projecting against the landmarks. Each chunk holds one
# float32 plane of (chunk x columns), so this bounds peak memory independent of n.
CHUNK = 6000

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


def confident_shared(columns: int) -> float:
    return min(CONFIDENT_SHARED_CAP, CONFIDENT_SHARED_FRACTION * columns)


def counts_against(
    block: np.ndarray, rows: np.ndarray, reference_rows: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Shared columns and matching columns between `rows` and `reference_rows`.

    Returned as (shared, matches), both (len(rows), len(reference_rows)) float32.
    Counting via matrix products rather than pairwise loops is what makes a
    22,000 x 1,500 comparison over 4,887 columns take seconds instead of hours.
    """
    right = block[reference_rows]
    right_valid = frame.is_base(right).astype(np.float32)
    shared = np.zeros((len(rows), len(reference_rows)), dtype=np.float32)
    matches = np.zeros_like(shared)

    for start in range(0, len(rows), CHUNK):
        stop = min(start + CHUNK, len(rows))
        left = block[rows[start:stop]]
        shared[start:stop] = frame.is_base(left).astype(np.float32) @ right_valid.T
        for code in range(1, 5):
            matches[start:stop] += (left == code).astype(np.float32) @ (
                right == code
            ).astype(np.float32).T
    return shared, matches


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


def eligible(block: np.ndarray, min_nt: int) -> np.ndarray:
    """Row indices carrying enough unambiguous material to place at all."""
    return np.flatnonzero(frame.is_base(block).sum(axis=1) >= min_nt)


def choose_landmarks(
    block: np.ndarray, rows: np.ndarray, min_shared: int, cap: int = LANDMARK_CAP
) -> np.ndarray:
    """Densely-covered rows whose pairwise distances are all defined.

    Greedy in descending coverage: the best-covered sequence is always a landmark,
    and each next candidate joins only if it overlaps every landmark already chosen.
    Whole genomes overlap each other completely, so in practice almost nothing is
    rejected — but the check has to be there, because one fragment admitted into the
    landmark set would put a NaN in the matrix being eigendecomposed.
    """
    coverage = frame.is_base(block[rows]).sum(axis=1)
    order = rows[np.argsort(-coverage, kind="stable")]
    candidates = order[: min(len(order), cap * 2)]

    shared, _ = counts_against(block, candidates, candidates)
    chosen: list[int] = []
    for index in range(len(candidates)):
        # The first candidate is the best-covered row, so it always qualifies; every
        # later one must overlap every landmark already chosen.
        if not chosen or np.all(shared[index, chosen] >= min_shared):
            chosen.append(index)
        if len(chosen) >= cap:
            break
    return candidates[np.array(chosen, dtype=np.int64)]


def landmark_matrix(
    block: np.ndarray, landmarks: np.ndarray, min_shared: int
) -> np.ndarray:
    """Complete square distance matrix over the landmarks. Raises if any pair is
    undefined, because that is a bug in `choose_landmarks`, not a data condition."""
    shared, matches = counts_against(block, landmarks, landmarks)
    distance = distance_from_counts(shared, matches, min_shared)
    np.fill_diagonal(distance, 0.0)
    if np.isnan(distance).any():
        raise ValueError(
            f"{int(np.isnan(distance).sum())} landmark pairs are undefined; "
            "choose_landmarks admitted a row it should have rejected"
        )
    return distance


def to_landmarks(
    block: np.ndarray, rows: np.ndarray, landmarks: np.ndarray, min_shared: int
) -> tuple[np.ndarray, np.ndarray]:
    """Each row's distances to every landmark, plus its shared-column counts."""
    shared, matches = counts_against(block, rows, landmarks)
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
