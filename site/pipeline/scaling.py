"""Figure set 2: one region's sequences placed by distance to each other.

Assembles what the browser needs per region — a coordinate per sequence, whether its
placement is confident, and enough diagnostics for the figure to state its own
limitations honestly (how much variance two dimensions captured, how non-Euclidean
the distances were, how many sequences could not be placed at all).
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
) -> dict:
    """Place every sequence in one region. `rows` indexes the alignment."""
    threshold = contract.min_nt(region)
    block = alignment.matrix[np.ix_(rows, columns)]

    placeable = distances.eligible(block, threshold)
    if len(placeable) < 3:
        return {
            "row": np.zeros(0, dtype=np.int64),
            "x": np.zeros(0, dtype=np.float32),
            "y": np.zeros(0, dtype=np.float32),
            "resolved": np.zeros(0, dtype=np.int32),
            "confident": np.zeros(0, dtype=bool),
            "landmarks": 0,
            "explained": 0.0,
            "negative_share": 0.0,
            "excluded": {"below_coverage": int(len(rows) - len(placeable))},
            "min_nt": threshold,
            "columns": int(len(columns)),
        }

    landmarks = distances.choose_landmarks(block, placeable, threshold)
    fitted = embed.Embedding(distances.landmark_matrix(block, landmarks, threshold))

    to_landmarks, shared = distances.to_landmarks(block, placeable, landmarks, threshold)
    coordinates = fitted.place(to_landmarks)
    resolved, confident = distances.confidence(to_landmarks, shared, len(columns))

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
    coordinates = embed.pin_orientation(
        coordinates, anchor, weights=confident.astype(np.float64)
    )

    return {
        "row": placeable,
        "x": coordinates[:, 0].astype(np.float32),
        "y": coordinates[:, 1].astype(np.float32),
        "resolved": resolved,
        "confident": confident,
        "landmarks": int(len(landmarks)),
        "explained": fitted.explained,
        "negative_share": fitted.negative_share,
        "excluded": {"below_coverage": int(len(rows) - len(placeable))},
        "min_nt": threshold,
        "columns": int(len(columns)),
    }
