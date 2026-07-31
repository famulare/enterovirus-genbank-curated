"""Load the curation ledger into the shapes the derive rules need.

Only `status == active` rows are ever returned. Retired and superseded rows are curation history:
honouring them would resurrect a judgement the curator has withdrawn, which is the reverse of the
D2 failure and just as wrong.
"""

from __future__ import annotations

import csv
from pathlib import Path

from enterovirus_genbank_curated.contracts import ACTIVE_STATUS, ContractError

EXCLUDING_DECISION_TYPES = frozenset({"membership_exclusion", "carve_exclusion"})


def _read_active(ledger_path: Path) -> list[dict[str, str]]:
    try:
        handle = ledger_path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ContractError(f"cannot read decision ledger {ledger_path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        required = {"decision_type", "accession", "field_name", "new_value", "status"}
        if not required <= set(reader.fieldnames or ()):
            raise ContractError(f"{ledger_path} must declare columns {sorted(required)}")
        return [row for row in reader if row["status"] == ACTIVE_STATUS]


def load_excluded_accessions(ledger_path: Path) -> frozenset[str]:
    """Accessions the ledger actively removes from the canonical carve."""
    return frozenset(
        row["accession"]
        for row in _read_active(ledger_path)
        if row["decision_type"] in EXCLUDING_DECISION_TYPES
    )


def load_active_decisions(ledger_path: Path) -> dict[str, dict[str, str]]:
    """`{accession: {field_name: new_value}}` for every active assertion.

    `validate_decision_ledger` has already refused two active assertions for the same subject and
    field, so flattening to one value per field is safe here rather than a silent last-wins. It is
    still asserted, because this function would otherwise depend on a check made somewhere else.
    """
    decisions: dict[str, dict[str, str]] = {}
    for row in _read_active(ledger_path):
        accession = row["accession"]
        if not accession:
            continue
        fields = decisions.setdefault(accession, {})
        if row["field_name"] in fields:
            raise ContractError(
                f"{accession} has two active assertions for {row['field_name']!r}; the ledger "
                f"contract forbids it and something has bypassed validation"
            )
        fields[row["field_name"]] = row["new_value"]
    return decisions


def load_ledger_rows(ledger_path: Path) -> list[dict[str, str]]:
    """Every ledger row, in file order, whatever its status.

    Deliberately not filtered. `curate/apply.py` has to account for retired and superseded rows too:
    "the curator withdrew this" is an outcome, and dropping those rows here would make them
    indistinguishable from rows the build silently failed to apply.
    """
    try:
        handle = ledger_path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ContractError(f"cannot read decision ledger {ledger_path}: {exc}") from exc
    with handle:
        return list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))
