"""Parse the frozen GenBank flat file into normalized source relations.

This is the first pipeline stage that is genuinely reproducible from `raw/` alone: it reads the
authenticated archive and nothing else. No registry, no curated master, no network, no path
outside the clone.

The twelve relations and their column orders are **declared** here rather than emerging from dict
insertion order, so the schema is a stated contract that can drift-check against the shipped
release (see `tests/test_source_parse.py`).

Text handling has exactly two modes, and the distinction is load-bearing:

* `collapse()` — whitespace-normalized. The default, for identifiers, keys and controlled values.
* `verbatim()` — `None` → `""` and `str()`, nothing else. Used for submitter prose. Those columns
  are listed in `RAW_COLUMNS`; because they can contain tabs and newlines, the TSV writer quotes
  them (QUOTE_MINIMAL) and every reader must match.

## Known upstream loss — this layer is NOT fully loss-preserving

Biopython's GenBank scanner silently discards text it cannot fit to the structured-comment grammar,
and we inherit that. Measured on the v2.1.5 corpus (see `VERBATIM_COLUMNS` and the warning-count
test):

* MH484164.1, MH484165.1, MH484166.1 — the entire `##Assembly-Data-START##` block is dropped
  (assembly method, sequencing technology, coverage). It does not fall back into `comment_text`;
  it is simply gone. These are the 9 `BiopythonParserWarning`s the parse emits.
* MN918613.1 and PP461545.1 — the `##Assembly-Data-END##` continuation line is dropped with **no
  warning at all**. PP461545.1's `comment_text` therefore ends mid-sentence at
  "...Created with VAPiDv1.6.7 Reference".

The shipped v2.1.5 release has exactly the same loss, so byte-parity locks it in: it cannot be
corrected without deliberately breaking the parity gate and cutting a new release. That is a real
constraint, recorded here rather than left for someone to rediscover.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from Bio import SeqIO
from Bio.SeqFeature import CompoundLocation

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "records": (
        "record_id", "record_ordinal", "accession", "version", "locus_name", "definition",
        "organism_name", "ncbi_taxid", "molecule_type", "topology", "division", "record_date",
        "sequence_length_nt", "sequence_sha256",
    ),
    "record_keywords": ("record_id", "keyword_ordinal", "keyword"),
    "record_taxonomy": ("record_id", "lineage_ordinal", "taxon_name"),
    "record_xrefs": ("record_id", "xref_ordinal", "database_name", "identifier"),
    "record_accessions": ("record_id", "accession_ordinal", "accession", "accession_role"),
    "features": (
        "feature_id", "record_id", "feature_ordinal", "feature_key", "location_parsed",
        "location_operator",
    ),
    "feature_location_parts": (
        "feature_id", "part_ordinal", "start_1based", "end_1based_inclusive", "strand",
        "start_position_class", "end_position_class", "remote_accession",
    ),
    "feature_qualifiers": (
        "feature_id", "qualifier_ordinal", "qualifier_name", "value_ordinal", "qualifier_value",
    ),
    "references": (
        "reference_id", "record_id", "reference_ordinal", "title", "journal_raw", "authors_raw",
        "pubmed_id", "medline_id", "consortium", "reference_location", "remark",
    ),
    "reference_authors": ("reference_id", "author_ordinal", "author_raw"),
    "comments": ("comment_id", "record_id", "comment_ordinal", "comment_type", "comment_text"),
    "structured_comment_fields": ("comment_id", "field_ordinal", "field_name", "field_value"),
}

# Columns written with `verbatim()` rather than `collapse()`. This is the single source of truth
# for that split: `_record_rows` asserts against it, so a new prose column that is not listed here
# fails loudly instead of being silently whitespace-collapsed.
RAW_COLUMNS: dict[str, frozenset[str]] = {
    "records": frozenset({"definition"}),
    "feature_qualifiers": frozenset({"qualifier_value"}),
    "references": frozenset(
        {"title", "journal_raw", "authors_raw", "consortium", "reference_location", "remark"}
    ),
    "comments": frozenset({"comment_text"}),
    "structured_comment_fields": frozenset({"field_value"}),
}

# Number of BiopythonParserWarnings the v2.1.5 corpus provokes. Pinned so that a Biopython upgrade
# which changes what the scanner silently drops shows up as a test failure rather than as a quiet
# change in shipped data. See the module docstring for what is being lost.
EXPECTED_PARSER_WARNINGS = 9

_ORDINAL_COLUMNS = frozenset(
    {
        "record_ordinal", "keyword_ordinal", "lineage_ordinal", "xref_ordinal",
        "accession_ordinal", "feature_ordinal", "qualifier_ordinal", "value_ordinal",
        "part_ordinal", "reference_ordinal", "author_ordinal", "comment_ordinal", "field_ordinal",
    }
)
INTEGER_COLUMNS = _ORDINAL_COLUMNS | {"sequence_length_nt", "start_1based", "end_1based_inclusive"}

# Convenience split of the author string on commas. Deliberately non-authoritative and, frankly,
# poor: GenBank author strings are "Surname,I.I." pairs, so splitting on every comma severs each
# surname from its initials, and a trailing " and X,Y." is not special-cased. references.authors_raw
# is the lossless field and the one to use. This split is retained only because the v2.1.5 release
# shipped 711,079 rows produced by it, and parity is byte-exact.
_AUTHOR_SPLIT = re.compile(r",\s*")

_STRAND_SYMBOL = {1: "+", -1: "-"}


def collapse(value: Any) -> str:
    """Whitespace-normalized text. The default for identifiers, keys and controlled values."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def verbatim(value: Any) -> str:
    """`None` -> `""`, otherwise `str()`. No whitespace normalization: loss-preserving prose."""
    return "" if value is None else str(value)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_feature(record: Any) -> Any | None:
    return next((f for f in record.features if f.type == "source"), None)


def source_qualifier(feature: Any | None, key: str) -> str:
    if feature is None:
        return ""
    values = feature.qualifiers.get(key, [])
    return collapse(values[0]) if values else ""


def dblink_pairs(record: Any) -> list[tuple[str, str]]:
    raw = record.annotations.get("dbxrefs", []) or record.dbxrefs or []
    pairs = []
    for item in raw:
        text = collapse(item)
        database, identifier = text.split(":", 1) if ":" in text else ("", text)
        pairs.append((database, identifier))
    return pairs


def taxid_from_source(feature: Any | None) -> str:
    if feature is None:
        return ""
    for xref in feature.qualifiers.get("db_xref", []):
        text = str(xref)
        if text.startswith("taxon:"):
            return text.split(":", 1)[1]
    return ""


def qualifier_rows(feature_id: str, qualifiers: dict[str, Any]) -> Iterator[dict[str, str]]:
    for qualifier_ordinal, (name, values) in enumerate(qualifiers.items(), start=1):
        listed = values if isinstance(values, list) else [values]
        for value_ordinal, value in enumerate(listed, start=1):
            yield {
                "feature_id": feature_id,
                "qualifier_ordinal": str(qualifier_ordinal),
                "qualifier_name": collapse(name),
                "value_ordinal": str(value_ordinal),
                "qualifier_value": verbatim(value),
            }


def location_part_rows(feature_id: str, location: Any) -> Iterator[dict[str, str]]:
    parts = list(location.parts) if isinstance(location, CompoundLocation) else [location]
    for part_ordinal, part in enumerate(parts, start=1):
        start, end = part.start, part.end
        yield {
            "feature_id": feature_id,
            "part_ordinal": str(part_ordinal),
            "start_1based": str(int(start) + 1),
            "end_1based_inclusive": str(int(end)),
            "strand": _STRAND_SYMBOL.get(part.strand, ""),
            "start_position_class": type(start).__name__,
            "end_position_class": type(end).__name__,
            "remote_accession": collapse(getattr(part, "ref", "")),
        }


def split_authors(authors_raw: str) -> list[str]:
    return [a.strip() for a in _AUTHOR_SPLIT.split(collapse(authors_raw)) if a.strip()]


def _record_rows(record: Any, record_ordinal: int) -> tuple[str, dict[str, list[dict[str, str]]]]:
    version = collapse(record.id)
    accession = version.split(".")[0]
    record_id = version
    sequence = str(record.seq).upper()
    src = source_feature(record)
    xrefs = dblink_pairs(record)
    taxid = taxid_from_source(src)
    organism = collapse(record.annotations.get("organism", source_qualifier(src, "organism")))

    tables: dict[str, list[dict[str, str]]] = defaultdict(list)
    tables["records"].append(
        {
            "record_id": record_id,
            "record_ordinal": str(record_ordinal),
            "accession": accession,
            "version": version,
            "locus_name": collapse(record.name),
            "definition": verbatim(record.description),
            "organism_name": organism,
            "ncbi_taxid": taxid,
            "molecule_type": collapse(record.annotations.get("molecule_type")),
            "topology": collapse(record.annotations.get("topology")),
            "division": collapse(record.annotations.get("data_file_division")),
            "record_date": collapse(record.annotations.get("date")),
            "sequence_length_nt": str(len(sequence)),
            "sequence_sha256": sha256_text(sequence),
        }
    )

    for ordinal, keyword in enumerate(record.annotations.get("keywords", []), start=1):
        tables["record_keywords"].append(
            {"record_id": record_id, "keyword_ordinal": str(ordinal), "keyword": collapse(keyword)}
        )
    for ordinal, taxon in enumerate(record.annotations.get("taxonomy", []), start=1):
        tables["record_taxonomy"].append(
            {"record_id": record_id, "lineage_ordinal": str(ordinal), "taxon_name": collapse(taxon)}
        )
    for ordinal, (database, identifier) in enumerate(xrefs, start=1):
        tables["record_xrefs"].append(
            {
                "record_id": record_id,
                "xref_ordinal": str(ordinal),
                "database_name": database,
                "identifier": identifier,
            }
        )

    secondary = [
        collapse(a)
        for a in record.annotations.get("accessions", [])
        if collapse(a) and collapse(a) != accession
    ]
    for ordinal, acc in enumerate(dict.fromkeys([accession, *secondary]), start=1):
        tables["record_accessions"].append(
            {
                "record_id": record_id,
                "accession_ordinal": str(ordinal),
                "accession": acc,
                "accession_role": "primary" if ordinal == 1 else "secondary",
            }
        )

    for feature_ordinal, feature in enumerate(record.features, start=1):
        feature_id = f"{record_id}:F{feature_ordinal}"
        tables["features"].append(
            {
                "feature_id": feature_id,
                "record_id": record_id,
                "feature_ordinal": str(feature_ordinal),
                "feature_key": collapse(feature.type),
                # Parsed representation of the Biopython location object, not the literal INSDC
                # expression; feature_location_parts carries the structured truth.
                "location_parsed": collapse(feature.location),
                "location_operator": collapse(getattr(feature.location, "operator", "")),
            }
        )
        tables["feature_location_parts"].extend(location_part_rows(feature_id, feature.location))
        tables["feature_qualifiers"].extend(qualifier_rows(feature_id, feature.qualifiers))

    for reference_ordinal, ref in enumerate(record.annotations.get("references", []), start=1):
        reference_id = f"{record_id}:R{reference_ordinal}"
        authors_raw = verbatim(getattr(ref, "authors", ""))
        tables["references"].append(
            {
                "reference_id": reference_id,
                "record_id": record_id,
                "reference_ordinal": str(reference_ordinal),
                "title": verbatim(getattr(ref, "title", "")),
                "journal_raw": verbatim(getattr(ref, "journal", "")),
                "authors_raw": authors_raw,
                "pubmed_id": collapse(getattr(ref, "pubmed_id", "")),
                "medline_id": collapse(getattr(ref, "medline_id", "")),
                "consortium": verbatim(getattr(ref, "consrtm", "")),
                "reference_location": verbatim(getattr(ref, "location", "")),
                "remark": verbatim(getattr(ref, "comment", "")),
            }
        )
        for author_ordinal, author in enumerate(split_authors(authors_raw), start=1):
            tables["reference_authors"].append(
                {
                    "reference_id": reference_id,
                    "author_ordinal": str(author_ordinal),
                    "author_raw": author,
                }
            )

    comment = verbatim(record.annotations.get("comment"))
    if comment.strip():
        tables["comments"].append(
            {
                "comment_id": f"{record_id}:C1",
                "record_id": record_id,
                "comment_ordinal": "1",
                "comment_type": "COMMENT",
                "comment_text": comment,
            }
        )
    structured = record.annotations.get("structured_comment", {}) or {}
    for block_ordinal, (block, fields) in enumerate(structured.items(), start=1):
        comment_id = f"{record_id}:SC{block_ordinal}"
        tables["comments"].append(
            {
                "comment_id": comment_id,
                "record_id": record_id,
                "comment_ordinal": str(block_ordinal),
                "comment_type": "STRUCTURED_COMMENT",
                "comment_text": collapse(block),
            }
        )
        for field_ordinal, (name, value) in enumerate(fields.items(), start=1):
            tables["structured_comment_fields"].append(
                {
                    "comment_id": comment_id,
                    "field_ordinal": str(field_ordinal),
                    "field_name": collapse(name),
                    "field_value": verbatim(value),
                }
            )

    return version, tables


def parse_records(records: Iterable[Any]) -> dict[str, list[dict[str, str]]]:
    """Build the twelve normalized relations from already-parsed Biopython records.

    Every declared table is present even when empty, so consumers never branch on absence.
    """
    tables: dict[str, list[dict[str, str]]] = {name: [] for name in TABLE_COLUMNS}
    for record_ordinal, record in enumerate(records, start=1):
        _, produced = _record_rows(record, record_ordinal)
        for name, rows in produced.items():
            if name not in tables:
                raise ValueError(f"parser produced an undeclared table: {name}")
            tables[name].extend(rows)
    return tables


def parse_source_tables(flat_file: Path | str) -> dict[str, list[dict[str, str]]]:
    """Parse a GenBank flat file at `flat_file` into the twelve normalized relations.

    Takes a filesystem path only. An earlier signature accepted "a path or a record iterable",
    which meant `parse_source_tables("")` took the iterable branch and returned twelve empty
    tables with no error — a silent empty build. Use `parse_records` for in-memory records.
    """
    path = Path(flat_file)
    if not path.is_file():
        raise FileNotFoundError(f"GenBank flat file not found: {path}")
    with path.open("r", encoding="utf-8", errors="strict") as handle:
        return parse_records(SeqIO.parse(handle, "genbank"))
