"""Assembles the per-selection figure artifacts the browser loads.

One file per selection. Rows are referenced by their index into `records.json`
rather than by accession, so the payload carries integers instead of repeated
strings and the browser can look up a full record without a second fetch.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import contract
import distances
import divergence
import frame
import scaling

SCHEMA = 1


def _ints(array: np.ndarray) -> list[int]:
    return [int(value) for value in array]


def selection_rows(
    selection: dict, alignment: frame.Alignment, by_accession: dict
) -> np.ndarray:
    restrict = selection["restrict"]
    if restrict is None:
        return np.arange(len(alignment.ids), dtype=np.int64)
    return np.array(
        [
            index
            for index, accession in enumerate(alignment.ids)
            if (by_accession.get(accession) or {}).get("virus_group") == restrict
        ],
        dtype=np.int64,
    )


@dataclass
class Population:
    """The rows one selection actually draws, resolved once.

    Every figure set reads this rather than re-deriving it, so the scatter, the map and
    the two trees cannot end up describing different populations of the same selection.
    """

    rows: np.ndarray
    accessions: list[str]
    record_rows: list[int]
    records: list[dict]
    orphaned: int


def resolve_population(
    selection: dict,
    alignment: frame.Alignment,
    records: list[dict],
    by_accession: dict,
    record_index: dict[str, int],
) -> Population:
    rows = selection_rows(selection, alignment, by_accession)
    accessions = [alignment.ids[index] for index in rows]

    # Rows whose accession is absent from the canonical table cannot be shown: the
    # figure has nothing to colour or label them with. Counted, never silently kept.
    placed = np.array(
        [index for index, accession in enumerate(accessions) if accession in record_index],
        dtype=np.int64,
    )
    orphaned = len(accessions) - len(placed)
    rows = rows[placed]
    accessions = [accessions[index] for index in placed]
    record_rows = [record_index[accession] for accession in accessions]
    return Population(
        rows=rows,
        accessions=accessions,
        record_rows=record_rows,
        records=[records[index] for index in record_rows],
        orphaned=orphaned,
    )


def build_selection(
    selection: dict,
    alignment: frame.Alignment,
    columns: dict[str, np.ndarray],
    population: Population,
) -> dict:
    rows = population.rows
    accessions = population.accessions
    record_rows = population.record_rows
    records_by_row = population.records
    orphaned = population.orphaned

    panels = {}
    for region in contract.DIVERGENCE_REGIONS:
        panel = divergence.build_region(
            alignment, rows, columns[region], selection, records_by_row, region, accessions
        )
        keep = panel["row"]
        panels[region] = {
            "record": [record_rows[index] for index in keep],
            # Unambiguous nucleotides this record carries in this region. A property of
            # record x region rather than of either figure, but shipped per block
            # because the two figures keep different row sets per region.
            "coverage": _ints(frame.coverage(alignment, columns[region])[rows][keep]),
            "comparable": _ints(panel["comparable"]),
            "assessable": _ints(panel["assessable"]),
            "synonymous": _ints(panel["synonymous"]),
            "nonsynonymous": _ints(panel["nonsynonymous"]),
            "indel_codons": _ints(panel["indel_codons"]),
            "indel_events": _ints(panel["indel_events"]),
            "frameshift": [int(index) for index, flag in enumerate(panel["frameshift"]) if flag],
            "reference": _ints(panel["reference"]),
            "jitter_x": _ints(panel["jitter_x"]),
            "jitter_y": _ints(panel["jitter_y"]),
            "references": panel["references"],
            "excluded": panel["excluded"],
            "codons": panel["codons"],
            "min_nt": panel["min_nt"],
        }

    distance = _distance_block(
        alignment, rows, columns, record_rows, contract.DISTANCE_REGIONS, distances.NUCLEOTIDE
    )
    protein_distance = _distance_block(
        alignment,
        rows,
        columns,
        record_rows,
        contract.PROTEIN_DISTANCE_REGIONS,
        distances.RESIDUE,
    )

    return {
        "schema": SCHEMA,
        "selection": selection["id"],
        "alignment": alignment.name,
        "frame": selection["frame"],
        "n_rows": int(len(rows)),
        "orphaned": orphaned,
        "jitter_scale": divergence.JITTER_SCALE,
        # Amplitude of the jitter, as a fraction of one count. The browser applies
        # offset = (jitter / jitter_scale) * jitter_amplitude / comparable.
        "jitter_amplitude": 0.25,
        "divergence": panels,
        "distance": distance,
        "protein_distance": protein_distance,
    }


def _distance_block(
    alignment: frame.Alignment,
    rows: np.ndarray,
    columns: dict[str, np.ndarray],
    record_rows: list[int],
    regions: tuple[str, ...],
    alphabet: distances.Alphabet,
) -> dict:
    """One scaling figure's regions. Nucleotide and residue space differ only in the
    alphabet, so they are emitted by one function and read by one decoder."""
    distance = {}
    for region in regions:
        placed = scaling.build_region(
            alignment, rows, columns[region], region, [], alphabet
        )
        keep = placed["row"]
        # Coverage is quoted in the figure's own unit, so a residue panel does not
        # report a nucleotide count beside a codon threshold.
        coverage = frame.coverage(alignment, columns[region])[rows]
        if alphabet is distances.RESIDUE:
            coverage = frame.is_residue(
                frame.residue_block(alignment.matrix[np.ix_(rows, columns[region])])
            ).sum(axis=1)
        distance[region] = {
            "record": [record_rows[index] for index in keep],
            "coverage": _ints(coverage[keep]),
            "resolved": _ints(placed["resolved"]),
            "thin": [int(i) for i, ok in enumerate(placed["confident"]) if not ok],
            "landmarks": placed["landmarks"],
            "excluded": placed["excluded"],
            "columns": placed["columns"],
            "min_nt": placed["min_nt"],
            # Which records are placed, how well, and against how many landmarks is
            # shared by both transforms; only the coordinates and the fit differ.
            "transforms": {
                name: {
                    # Four decimals is finer than a 720px panel can resolve, and keeps
                    # the payload from carrying float noise that churns the diff.
                    "x": [round(float(v), 4) for v in fit["x"]],
                    "y": [round(float(v), 4) for v in fit["y"]],
                    "explained": round(fit["explained"], 4),
                    "negative_share": round(fit["negative_share"], 4),
                }
                for name, fit in placed["transforms"].items()
            },
            "unit": placed["unit"],
        }
    return distance
