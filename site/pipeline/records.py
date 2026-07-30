"""The shared record table every figure set reads.

One entry per canonical sequence, carrying all twenty-four curated fields plus the
derived traits. Emitted once rather than per selection, because `all` already
contains every other selection and repeating the payload five times would be the
bulk of the site's weight.

Columns are dictionary-encoded when that actually helps. For a field like `country`
(131 distinct values over 22,498 records) the table plus an index array is a large
saving; for `isolate_name` (15,378 distinct over 17,283) it would cost more than it
saves, so those stay raw.
"""

from __future__ import annotations

import contract
import traits

SCHEMA = 1

# Encode as a dictionary only when distinct values are at most this fraction of
# the non-empty population. Above it, the index array outweighs the table.
DICTIONARY_MAX_RATIO = 0.5


def _encode_column(values: list[str]) -> dict:
    distinct = sorted({value for value in values if value})
    present = sum(1 for value in values if value)
    if present and len(distinct) / present > DICTIONARY_MAX_RATIO:
        return {"kind": "raw", "values": values}
    # Index 0 is reserved for empty, so a missing value needs no separate mask.
    lookup = {value: index + 1 for index, value in enumerate(distinct)}
    return {
        "kind": "dictionary",
        "table": distinct,
        "index": [lookup.get(value, 0) for value in values],
    }


def build(records: list[dict]) -> dict:
    """The record table, in canonical-file order so indices are stable."""
    columns: dict[str, dict] = {}
    for field in contract.CANONICAL_COLUMNS:
        if field == contract.KEY_ACCESSION:
            continue
        columns[field] = _encode_column([str(record[field] or "") for record in records])

    columns["species"] = _encode_column([record["species"] for record in records])

    year = [record["collection_year"] for record in records]
    columns["collection_year"] = {
        "kind": "numeric",
        # Two decimal places is finer than any date in the release supports, and
        # keeps the payload from carrying float noise.
        "values": [None if value is None else round(value, 2) for value in year],
    }

    return {
        "schema": SCHEMA,
        "n": len(records),
        # Which columns this site computed rather than read, so the inspector can say
        # so instead of listing them among the release's own fields.
        "derived": sorted(DERIVED_LABELS),
        "accession": [record["accession"] for record in records],
        "manual_decision": [
            index for index, record in enumerate(records) if record["has_manual_decision"]
        ],
        "columns": columns,
        "labels": _field_labels(),
    }


# Fields whose value this site computed rather than read, and the label each takes in
# the record inspector.
#
# `collection_year` needs a label of its own. Its *trait* label is "Collection date",
# because that is what a reader wants to colour by — but the raw `collection_date`
# column also renders as "Collection date", so the inspector showed two rows under one
# name with different values: `Sep-2010` beside `2010.71`, `2020/2021` beside its
# midpoint. Same underlying fact, two representations, and no way to tell which was
# which.
DERIVED_LABELS = {
    "species": "Species",
    "collection_year": "Collection date, as a decimal year",
}


def _field_labels() -> dict[str, str]:
    """Human-readable names for the pinned detail view, in canonical order."""
    overrides = {trait["id"]: trait["label"] for trait in contract.TRAITS}
    labels = {}
    for field in contract.CANONICAL_COLUMNS:
        labels[field] = overrides.get(field) or field.replace("_", " ").capitalize()
    labels.update(DERIVED_LABELS)
    return labels


def index_by_accession(records: list[dict]) -> dict[str, int]:
    return {record["accession"]: index for index, record in enumerate(records)}


def load() -> tuple[list[dict], dict[str, dict]]:
    return traits.build_records()
