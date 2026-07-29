"""Canonical metadata, plus the traits that have to be derived from it.

Three traits are not columns in `final/canonical/`:

- `species` — the canonical table ships no species field, so it is read out of the
  GenBank taxonomy lineage. See the `# SWITCHOVER:` note in contract.py.
- `type_concordance` — whether the curated `virus_type` agrees with the alignment
  the record was actually placed in. Disagreement is the misclassification signal
  the site exists to surface, so it is a first-class colorable trait.
- `collection_year` — a decimal year. `collection_date` is not ISO-normalized
  upstream yet, so this parser handles more shapes than it eventually should.
"""

from __future__ import annotations

import csv
import gzip
import re

import contract

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO = re.compile(r"^(\d{4})(?:-(\d{2})(?:-(\d{2}))?)?$")
_MON_YEAR = re.compile(r"^([A-Za-z]{3})-(\d{4})$")
_RANGE = re.compile(r"^(\d{4})\s*/\s*(\d{4})$")
_DAYS_BEFORE_MONTH = (0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334)


def read_canonical() -> list[dict[str, str]]:
    with gzip.open(contract.CANONICAL_METADATA, "rt", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        raise ValueError("canonical metadata is empty")
    missing = set(contract.CANONICAL_COLUMNS) - set(rows[0])
    if missing:
        raise ValueError(f"canonical metadata is missing declared columns: {sorted(missing)}")
    extra = set(rows[0]) - set(contract.CANONICAL_COLUMNS)
    if extra:
        raise ValueError(
            f"canonical metadata has undeclared columns {sorted(extra)}. Add them to "
            "contract.CANONICAL_COLUMNS (and TRAITS if colorable) before rebuilding."
        )
    return rows


def derive_species() -> dict[str, str]:
    """version -> species label (EV-A .. RV-C), or `unresolved`.

    The lineage uses post-2023 ICTV binomials (`Enterovirus coxsackiepol`), which
    is not how this field is reported anywhere else, hence the explicit mapping.
    The species-rank taxon is the one immediately below the genus.
    """
    lineage: dict[str, dict[int, str]] = {}
    with gzip.open(contract.RECORD_TAXONOMY, "rt", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            ranks = lineage.setdefault(row["record_id"], {})
            ranks[int(row["lineage_ordinal"])] = row["taxon_name"]

    out: dict[str, str] = {}
    for version, ranks in lineage.items():
        ordinals = sorted(ranks)
        label = contract.SPECIES_UNRESOLVED
        for position, ordinal in enumerate(ordinals):
            if ranks[ordinal] in contract.GENUS_TAXA and position + 1 < len(ordinals):
                child = ranks[ordinals[position + 1]]
                label = contract.SPECIES_BINOMIAL.get(child, contract.SPECIES_UNRESOLVED)
                break
        out[version] = label
    return out


def parse_collection_date(value: str) -> float | None:
    """Decimal year, or None when nothing can be parsed.

    Handles the shapes actually present upstream today: ISO year / year-month /
    full date, `Mon-YYYY`, and `YYYY/YYYY` ranges. A range resolves to its
    midpoint; a year-only value resolves to mid-year, so a year-precision record
    never plots as though it were collected on 1 January.
    """
    value = (value or "").strip()
    if not value:
        return None

    match = _ISO.match(value)
    if match:
        year = int(match.group(1))
        if match.group(3):
            month, day = int(match.group(2)), int(match.group(3))
            return year + (_DAYS_BEFORE_MONTH[month - 1] + day - 0.5) / 365.0
        if match.group(2):
            month = int(match.group(2))
            return year + (_DAYS_BEFORE_MONTH[month - 1] + 15) / 365.0
        return year + 0.5

    match = _MON_YEAR.match(value)
    if match:
        month = MONTHS.get(match.group(1).lower())
        if month:
            return int(match.group(2)) + (_DAYS_BEFORE_MONTH[month - 1] + 15) / 365.0
        return None

    match = _RANGE.match(value)
    if match:
        return (int(match.group(1)) + int(match.group(2)) + 1) / 2.0

    return None


def manual_decision_accessions() -> set[str]:
    with gzip.open(contract.MANUAL_DECISIONS, "rt", newline="") as handle:
        return {
            row["accession"] for row in csv.DictReader(handle, delimiter="\t") if row["accession"]
        }


def concordance(record: dict[str, str], selection_id: str, aligned: bool) -> str:
    """Curated virus_type against the alignment the record was placed in.

    Only meaningful for the per-serotype alignments, whose membership is a
    sequence-based typing claim that can disagree with the curated field. The
    genus-wide alignment makes no serotype claim, so its rows are concordant by
    construction.
    """
    if not aligned:
        return contract.UNALIGNED
    if selection_id not in contract.SABIN_REFERENCE:
        return contract.CONCORDANT
    return contract.CONCORDANT if record["virus_type"] == selection_id else contract.DISCORDANT


def build_records() -> tuple[list[dict], dict[str, dict]]:
    """Canonical rows with derived traits attached, plus an accession index."""
    rows = read_canonical()
    species = derive_species()
    decided = manual_decision_accessions()

    records = []
    for row in rows:
        record = dict(row)
        record["species"] = species.get(row["version"], contract.SPECIES_UNRESOLVED)
        record["collection_year"] = parse_collection_date(row["collection_date"])
        record["has_manual_decision"] = row["accession"] in decided
        records.append(record)
    return records, {record["accession"]: record for record in records}
