"""Assembles the per-selection figure artifacts the browser loads.

One file per selection. Rows are referenced by their index into `records.json`
rather than by accession, so the payload carries integers instead of repeated
strings and the browser can look up a full record without a second fetch.
"""

from __future__ import annotations

import numpy as np

import contract
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


def build_selection(
    selection: dict,
    alignment: frame.Alignment,
    columns: dict[str, np.ndarray],
    records: list[dict],
    by_accession: dict,
    record_index: dict[str, int],
) -> dict:
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
    records_by_row = [records[index] for index in record_rows]

    panels = {}
    for region in contract.DIVERGENCE_REGIONS:
        panel = divergence.build_region(
            alignment, rows, columns[region], selection, records_by_row, region, accessions
        )
        keep = panel["row"]
        panels[region] = {
            "record": [record_rows[index] for index in keep],
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

    distance = {}
    for region in contract.DISTANCE_REGIONS:
        placed = scaling.build_region(alignment, rows, columns[region], region, accessions)
        keep = placed["row"]
        distance[region] = {
            "record": [record_rows[index] for index in keep],
            # Four decimals is finer than a 720px panel can resolve, and keeps the
            # payload from carrying float noise that would churn the committed diff.
            "x": [round(float(v), 4) for v in placed["x"]],
            "y": [round(float(v), 4) for v in placed["y"]],
            "resolved": _ints(placed["resolved"]),
            "thin": [int(i) for i, ok in enumerate(placed["confident"]) if not ok],
            "landmarks": placed["landmarks"],
            "explained": round(placed["explained"], 4),
            "negative_share": round(placed["negative_share"], 4),
            "excluded": placed["excluded"],
            "columns": placed["columns"],
            "min_nt": placed["min_nt"],
        }

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
    }
