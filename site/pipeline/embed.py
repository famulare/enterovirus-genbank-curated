"""Classical multidimensional scaling, with out-of-sample placement.

Landmarks are embedded exactly by classical MDS — double-center the squared distance
matrix, eigendecompose, keep two dimensions. Every other sequence is then placed by
the Nyström extension: given its squared distances to the landmarks, it lands where a
landmark with that distance profile would.

Classical rather than stress-minimizing (SMACOF). At 22,000 points SMACOF does not
converge in reasonable time, and its advantage is local structure — whereas the
question this figure answers is global: does this sequence sit with its own type.
Classical MDS is also deterministic, which matters because the artifacts are
committed and a rebuild must not move every point.

Orientation is pinned for the same reason: eigenvector signs are arbitrary, so an
unpinned embedding flips left-right or top-bottom between rebuilds and the committed
artifact churns for no reason.
"""

from __future__ import annotations

import numpy as np

DIMENSIONS = 2


def _double_center(squared: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    """Gower's transform. Returns the Gram matrix, the row means, and the grand mean,
    because the out-of-sample projection needs the latter two."""
    row_means = squared.mean(axis=1)
    grand_mean = float(squared.mean())
    gram = -0.5 * (squared - row_means[:, None] - row_means[None, :] + grand_mean)
    return gram, row_means, grand_mean


# Available dissimilarity transforms. `linear` scales the distances as given;
# `sqrt` scales their square roots, which is materially different rather than
# cosmetic.
#
# Masked Hamming distance is not Euclidean, so some of the geometry cannot be drawn
# in a plane at all — up to 44% of it in the 3'NCR. Taking the square root usually
# fixes that: measured on this release the non-Euclidean share falls from 0.199 to
# 0.037 (PV1 5'NCR), 0.436 to 0.159 (PV1 3'NCR), and to exactly zero for the
# non-polio 5'NCR and P1, meaning those become perfectly embeddable.
#
# The cost is that two dimensions then carry less of the variance — 0.61 to 0.51 for
# PV1 P1. That is not a real loss. Under `linear` part of that 0.61 was propped up by
# a geometry a plane could not honestly represent; under `sqrt` the geometry is sound
# and the variance is spread across dimensions that genuinely exist.
TRANSFORMS = ("linear", "sqrt")


class Embedding:
    """A fitted landmark embedding that can place new points."""

    def __init__(self, distance: np.ndarray, transform: str = "linear"):
        if transform not in TRANSFORMS:
            raise ValueError(f"unknown transform {transform!r}")
        self.transform = transform
        # Classical scaling decomposes the SQUARED dissimilarities, so scaling the
        # square roots means feeding the distances through unsquared.
        squared = (
            np.square(distance.astype(np.float64))
            if transform == "linear"
            else distance.astype(np.float64).copy()
        )
        gram, self._row_means, self._grand_mean = _double_center(squared)

        # Symmetric by construction, so eigh — faster than eig and returns real
        # eigenvalues in ascending order.
        values, vectors = np.linalg.eigh(gram)
        order = np.argsort(-values)[:DIMENSIONS]
        self.values = np.maximum(values[order], 0.0)
        self.vectors = vectors[:, order]
        self.landmark_coordinates = self.vectors * np.sqrt(self.values)

        total = float(np.maximum(values, 0.0).sum())
        self.explained = (
            float(self.values.sum() / total) if total > 0 else 0.0
        )
        # A negative trailing eigenvalue means the distances are not Euclidean, which
        # masked Hamming distances need not be. Reported rather than hidden: it bounds
        # how much of the geometry two dimensions can honestly show.
        self.negative_share = (
            float(-np.minimum(values, 0.0).sum() / total) if total > 0 else 0.0
        )

    def place(self, distance_to_landmarks: np.ndarray) -> np.ndarray:
        """(n, L) distances, NaN where undefined -> (n, 2) coordinates.

        An undefined entry is filled with that landmark's mean distance, which is the
        least-committal value available: it pulls the point toward the centroid rather
        than inventing a position. `distances.confidence` records how many entries had
        to be filled so the figure can mark the point.
        """
        # An undefined entry is filled with the least-committal value available: the
        # value whose transform equals that landmark's mean, which pulls the point
        # toward the centroid rather than inventing a position.
        typical = (
            np.sqrt(np.maximum(self._row_means, 0.0))
            if self.transform == "linear"
            else np.maximum(self._row_means, 0.0)
        )
        filled = np.where(np.isnan(distance_to_landmarks), typical[None, :], distance_to_landmarks)
        squared = (
            np.square(filled.astype(np.float64))
            if self.transform == "linear"
            else filled.astype(np.float64)
        )
        centered = -0.5 * (
            squared
            - squared.mean(axis=1)[:, None]
            - self._row_means[None, :]
            + self._grand_mean
        )
        scale = np.where(self.values > 0, np.sqrt(self.values), 1.0)
        return (centered @ self.vectors) / scale


def pin_orientation(
    coordinates: np.ndarray, anchor: int | None, weights: np.ndarray | None = None
) -> np.ndarray:
    """Make the sign of each axis reproducible across rebuilds.

    Eigenvector signs are arbitrary. With an anchor — the Sabin reference, say — flip
    so it sits in the lower-left quadrant. Without one, flip so the weighted center of
    mass does, which is stable as long as the population is.
    """
    flipped = coordinates.copy()
    for axis in range(flipped.shape[1]):
        if anchor is not None:
            reference = flipped[anchor, axis]
        elif weights is not None and weights.sum() > 0:
            reference = float(np.average(flipped[:, axis], weights=weights))
        else:
            reference = float(flipped[:, axis].mean())
        # Ties would be decided by floating-point noise, so break them on the axis's
        # own skew instead, which is a property of the data.
        if abs(reference) < 1e-12:
            reference = float(np.sum(np.sign(flipped[:, axis]) * flipped[:, axis] ** 2))
        if reference > 0:
            flipped[:, axis] = -flipped[:, axis]
    return flipped
