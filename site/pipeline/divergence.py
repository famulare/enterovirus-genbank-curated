"""Figure set 1: synonymous against non-synonymous divergence from a reference.

Per record, per coding region:

  comparable codons   codons where query and reference BOTH carry three
                      unambiguous bases. Leading and trailing tails therefore cost
                      coverage rather than counting as difference, and an ambiguity
                      code reduces the denominator instead of inventing a mismatch.
  indel codons        codons, inside the span between the first and last comparable
                      position, holding at least one position where exactly one of
                      the two sequences has material. Disjoint from comparable
                      codons by construction: a comparable codon has material on
                      both sides at all three positions.
  assessable codons   comparable + indel codons. THE DENOMINATOR of both axes.
  synonymous          comparable codons whose nucleotides differ but whose
                      translation does not. One count per codon, however many of
                      its three positions differ.
  non-synonymous      comparable codons whose translation differs, plus every indel
                      codon.
  frameshift          any maximal indel run whose length is not a multiple of three.
                      Such a record is flagged rather than translated downstream.

Counting indels per affected codon rather than per event, over a denominator that
includes them, is what keeps both axes inside 0-1 with x + y <= 1. Charging one
count per indel *event* against a comparable-codon denominator does not: a patchy
fragment can span 900 nt while contributing only 68 comparable codons, and its
non-synonymous rate then exceeds 1.

Both axes are a count divided by the assessable-codon count, so they share one
0-1 scale and a VP1 fragment is comparable to a whole genome.

This is NOT dN/dS. There is no per-synonymous-site or per-non-synonymous-site
normalization and no multiple-hit correction, and it is not an evolutionary rate.
"""

from __future__ import annotations

import hashlib

import numpy as np

import contract
import frame
import reference

# Rows processed at once. The genus-wide polyprotein block is 9,117 columns, so a
# full-population boolean intermediate would be a few hundred megabytes; chunking
# keeps peak memory flat without measurably slowing the vectorized work.
CHUNK = 4000

# Jitter is stored as hundredths of the full amplitude so the browser can apply
# exactly the offset the build chose, without reimplementing a hash. Amplitude is a
# quarter of one count, per contract.
JITTER_SCALE = 100


def _jitter(accessions: list[str], region: str) -> tuple[np.ndarray, np.ndarray]:
    """Deterministic per-record offsets in [-100, 100], stable across rebuilds."""
    x = np.empty(len(accessions), dtype=np.int8)
    y = np.empty(len(accessions), dtype=np.int8)
    for index, accession in enumerate(accessions):
        digest = hashlib.sha256(f"{accession}|{region}".encode()).digest()
        x[index] = digest[0] % (2 * JITTER_SCALE + 1) - JITTER_SCALE
        y[index] = digest[1] % (2 * JITTER_SCALE + 1) - JITTER_SCALE
    return x, y


def _span_mask(comparable_nt: np.ndarray) -> np.ndarray:
    """True between each row's first and last comparable nucleotide, inclusive.

    Indels are only counted inside this span. Outside it the query simply has no
    material, which is missing data rather than a deletion.
    """
    width = comparable_nt.shape[1]
    positions = np.arange(width)
    any_covered = comparable_nt.any(axis=1)
    first = np.where(any_covered, comparable_nt.argmax(axis=1), width)
    last = np.where(any_covered, width - 1 - comparable_nt[:, ::-1].argmax(axis=1), -1)
    return (positions >= first[:, None]) & (positions <= last[:, None])


def measure(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: np.ndarray,
    refs: reference.References,
) -> dict[str, np.ndarray]:
    """Counts per row. Every returned array is aligned to `rows`."""
    total = len(rows)
    out = {
        "comparable": np.zeros(total, dtype=np.int32),
        "assessable": np.zeros(total, dtype=np.int32),
        "synonymous": np.zeros(total, dtype=np.int32),
        "nonsynonymous": np.zeros(total, dtype=np.int32),
        "indel_codons": np.zeros(total, dtype=np.int32),
        "indel_events": np.zeros(total, dtype=np.int32),
        "frameshift": np.zeros(total, dtype=bool),
    }
    ref_aa = frame.translate(frame.as_codons(refs.sequences))
    ref_codons = frame.as_codons(refs.sequences)

    for start in range(0, total, CHUNK):
        stop = min(start + CHUNK, total)
        slot = refs.row_index[start:stop]
        usable = slot >= 0
        if not usable.any():
            continue

        block = alignment.matrix[np.ix_(rows[start:stop], columns)]
        ref_block = refs.sequences[np.where(usable, slot, 0)]

        # Comparability needs an unambiguous base on both sides; indel detection
        # needs only material, so an ambiguity code lowers the denominator without
        # ever being mistaken for a deletion.
        comparable_nt = frame.is_base(block) & frame.is_base(ref_block) & usable[:, None]
        query_material = frame.has_material(block)
        ref_material = frame.has_material(ref_block)

        # --- codon-level substitution classification
        q_codons = frame.as_codons(block)
        r_codons = ref_codons[np.where(usable, slot, 0)]
        comparable = frame.as_codons(comparable_nt).all(axis=2)

        differs = (q_codons != r_codons).any(axis=2) & comparable
        same_aa = frame.translate(q_codons) == ref_aa[np.where(usable, slot, 0)]

        comparable_count = comparable.sum(axis=1)
        out["comparable"][start:stop] = comparable_count
        out["synonymous"][start:stop] = (differs & same_aa).sum(axis=1)
        nonsyn = (differs & ~same_aa).sum(axis=1)

        # --- indels inside the covered span
        span = _span_mask(comparable_nt)
        deletions = span & ref_material & ~query_material
        insertions = span & query_material & ~ref_material

        # Charged per affected codon, so the count shares the denominator's units.
        indel_nt = deletions | insertions
        indel_codons = frame.as_codons(indel_nt).any(axis=2).sum(axis=1)

        # Events are still counted, but only to detect a shifted reading frame and to
        # report the record's indel structure in the detail view.
        del_runs, del_shift = frame.run_stats(deletions)
        ins_runs, ins_shift = frame.run_stats(insertions)

        out["indel_codons"][start:stop] = indel_codons
        out["indel_events"][start:stop] = del_runs + ins_runs
        out["frameshift"][start:stop] = del_shift | ins_shift
        out["nonsynonymous"][start:stop] = nonsyn + indel_codons
        out["assessable"][start:stop] = comparable_count + indel_codons

    return out


def build_region(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: np.ndarray,
    selection: dict,
    records_by_row: list[dict],
    region: str,
    accessions: list[str],
) -> dict:
    """One region's panel: only rows clearing the coverage floor are emitted."""
    refs = reference.resolve(
        alignment, rows, columns, selection, records_by_row, region
    )
    counts = measure(alignment, rows, columns, refs)

    threshold = contract.min_nt(region)
    keep = np.flatnonzero((counts["comparable"] * 3 >= threshold) & (refs.row_index >= 0))

    kept_accessions = [accessions[i] for i in keep]
    jitter_x, jitter_y = _jitter(kept_accessions, region)

    excluded_coverage = int(
        ((counts["comparable"] * 3 < threshold) & (refs.row_index >= 0)).sum()
    )

    return {
        "row": keep.astype(np.int32),
        "comparable": counts["comparable"][keep],
        "assessable": counts["assessable"][keep],
        "synonymous": counts["synonymous"][keep],
        "nonsynonymous": counts["nonsynonymous"][keep],
        "indel_codons": counts["indel_codons"][keep],
        "indel_events": counts["indel_events"][keep],
        "frameshift": counts["frameshift"][keep],
        "reference": refs.row_index[keep].astype(np.int32),
        "jitter_x": jitter_x,
        "jitter_y": jitter_y,
        "references": [
            {"kind": kind, "label": label}
            for kind, label in zip(refs.kinds, refs.labels, strict=True)
        ],
        "excluded": {
            "below_coverage": excluded_coverage,
            "no_reference": refs.unresolved(),
        },
        "columns": int(len(columns)),
        "codons": int(len(columns) // 3),
        "min_nt": threshold,
    }
