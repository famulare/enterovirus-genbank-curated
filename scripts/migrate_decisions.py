#!/usr/bin/env python3
"""Normalize legacy CSV/TSV decision files into the public ledger contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    DECISIONS_SCHEMA_PATH,
    LEDGER_SORT_COLUMNS,
    ContractError,
    DecisionContract,
    load_decision_contract,
    validate_decision_ledger,
)

DEFAULTS = {
    "accession": "",
    "reason": "",
    "evidence_reference": "",
    "confirmed_by": "",
    "status": "active",
    "effective_from": "",
    "effective_through": "",
    "notes": "",
}

ID_PAYLOAD_COLUMNS = (
    "decision_type",
    "subject_key",
    "field_name",
    "new_value",
    "source_artifact",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--drop-columns",
        default="",
        help=(
            "comma-separated legacy columns that are known to be out of scope and may be "
            "discarded; any other unmapped column is a hard error"
        ),
    )
    return parser.parse_args()


def delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","


def stable_decision_id(row: dict[str, str]) -> str:
    payload = "\x1f".join(row[key] for key in ID_PAYLOAD_COLUMNS)
    return "D-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def normalize_row(raw: dict[str, str], source: Path, contract: DecisionContract) -> dict[str, str]:
    row = {key: (raw.get(key) or DEFAULTS.get(key, "")).strip() for key in contract.columns}
    row["subject_key"] = row["subject_key"] or row["accession"]
    row["source_artifact"] = row["source_artifact"] or source.as_posix()
    if not row["decision_id"]:
        row["decision_id"] = stable_decision_id(row)
    return row


def read_source(
    path: Path, contract: DecisionContract, droppable: frozenset[str]
) -> list[dict[str, str]]:
    """Read one legacy file, refusing to silently discard columns it does not understand."""
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter_for(path))
        fieldnames = tuple(reader.fieldnames or ())
        if not fieldnames:
            raise ContractError(f"{path} has no header row")
        unmapped = sorted(set(fieldnames) - set(contract.columns) - droppable)
        if unmapped:
            raise ContractError(
                f"{path} has columns with no ledger destination: {unmapped}. Map them into the "
                f"ledger contract or pass --drop-columns to discard them explicitly."
            )
        return [normalize_row(raw, path, contract) for raw in reader]


def main() -> int:
    args = parse_args()
    contract = load_decision_contract(args.repository_root.resolve() / DECISIONS_SCHEMA_PATH)
    droppable = frozenset(name.strip() for name in args.drop_columns.split(",") if name.strip())

    rows: list[dict[str, str]] = []
    for path in args.inputs:
        rows.extend(read_source(path, contract, droppable))

    for row in rows:
        for column, value in row.items():
            if any(character in value for character in "\t\r\n"):
                raise ContractError(
                    f"decision {row['decision_id']} field {column!r} contains a tab or newline; "
                    f"the ledger is plain tab-delimited text and cannot represent it"
                )

    rows.sort(key=lambda row: tuple(row[column] for column in LEDGER_SORT_COLUMNS))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(contract.columns), delimiter="\t", quoting=csv.QUOTE_NONE
        )
        writer.writeheader()
        writer.writerows(rows)

    summary = validate_decision_ledger(args.output, contract)
    print(f"wrote {summary.rows} decisions ({summary.active_rows} active) to {args.output}")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except ContractError as error:
        print(f"migration failed: {error}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)
