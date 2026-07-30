"""Figure sets 2 and 4: one region's sequences placed by distance to each other.

Assembles what the browser needs per region — a coordinate per sequence, whether its
placement is confident, and enough diagnostics for the figure to state its own
limitations honestly (how much variance two dimensions captured, how non-Euclidean
the distances were, how many sequences could not be placed at all).

Nucleotide and residue space are the same procedure over the same metric, so this module
is parameterized over the alphabet rather than written twice. What differs between the
two figures is only what a difference means: in residue space a synonymous change is
invisible by construction, so two sequences can coincide without being the same
sequence.
"""

from __future__ import annotations

import numpy as np

import contract
import distances
import embed
import frame


def build_region(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: np.ndarray,
    region: str,
    accessions: list[str],
    alphabet: distances.Alphabet = distances.NUCLEOTIDE,
) -> dict:
    """Place every sequence in one region. `rows` indexes the alignment."""
    block, threshold, width = distances.in_alphabet(
        alignment.matrix[np.ix_(rows, columns)],
        contract.min_nt(region),
        int(len(columns)),
        alphabet,
    )

    placeable = distances.eligible(block, threshold, alphabet)
    if len(placeable) < 3:
        return {
            "row": np.zeros(0, dtype=np.int64),
            "transforms": {
                transform: {
                    "x": np.zeros(0, dtype=np.float32),
                    "y": np.zeros(0, dtype=np.float32),
                    "explained": 0.0,
                    "negative_share": 0.0,
                }
                for transform in embed.TRANSFORMS
            },
            "resolved": np.zeros(0, dtype=np.int32),
            "confident": np.zeros(0, dtype=bool),
            "landmarks": 0,
            "excluded": {"below_coverage": int(len(rows) - len(placeable))},
            "min_nt": threshold,
            "columns": width,
            "unit": alphabet.unit,
        }

    # Pin on Sabin where the alignment carries it, so poliovirus panels always open
    # with the vaccine reference in the same corner. Otherwise pin on the
    # confidently-placed centre of mass, which is stable for a stable population.
    anchor = None
    for accession in contract.SABIN_REFERENCE.values():
        if accession in alignment.index:
            target = alignment.index[accession]
            hits = np.flatnonzero(rows[placeable] == target)
            if len(hits):
                anchor = int(hits[0])
                break

    landmarks = distances.comparable_set(
        block,
        placeable,
        threshold,
        cap=distances.LANDMARK_CAP,
        # Requiring the orientation anchor makes the pinning exact rather than
        # conditional on the anchor happening to survive the greedy.
        required=None if anchor is None else int(placeable[anchor]),
        alphabet=alphabet,
    )
    landmark_distance = distances.complete_matrix(block, landmarks, threshold, alphabet)
    to_landmarks, shared = distances.to_landmarks(
        block, placeable, landmarks, threshold, alphabet
    )
    resolved, confident = distances.confidence(to_landmarks, shared, width)

    # Both transforms, from one landmark matrix and one set of projections. The
    # expensive work is the distance computation, which they share; fitting is a
    # decomposition of a few hundred squared values.
    transforms = {}
    for transform in embed.TRANSFORMS:
        fitted = embed.Embedding(landmark_distance, transform)
        coordinates = embed.pin_orientation(
            fitted.place(to_landmarks), anchor, weights=confident.astype(np.float64)
        )
        transforms[transform] = {
            "x": coordinates[:, 0].astype(np.float32),
            "y": coordinates[:, 1].astype(np.float32),
            "explained": fitted.explained,
            "negative_share": fitted.negative_share,
        }

    return {
        "row": placeable,
        "transforms": transforms,
        "resolved": resolved,
        "confident": confident,
        "landmarks": int(len(landmarks)),
        "excluded": {"below_coverage": int(len(rows) - len(placeable))},
        "min_nt": threshold,
        "columns": width,
        "unit": alphabet.unit,
    }
