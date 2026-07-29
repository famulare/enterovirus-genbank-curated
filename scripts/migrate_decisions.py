#!/usr/bin/env python3
"""Normalize legacy CSV/TSV decision files into the public ledger contract."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path

from enterovirus_genbank_curated.contracts import DECISION_COLUMNS, validate_decision_ledger

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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("inputs", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def delimiter_for(path: Path) -> str:
    return "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","


def stable_decision_id(row: dict[str, str]) -> str:
    payload = "\x1f".join(
        row[key]
        for key in (
            "decision_type",
            "subject_key",
            "field_name",
            "new_value",
            "source_artifact",
        )
    )
    return "D-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]


def normalize_row(raw: dict[str, str], source: Path) -> dict[str, str]:
    row = {key: (raw.get(key) or DEFAULTS.get(key, "")).strip() for key in DECISION_COLUMNS}
    row["subject_key"] = row["subject_key"] or row["accession"]
    row["source_artifact"] = row["source_artifact"] or source.as_posix()
    if not row["decision_id"]:
        row["decision_id"] = stable_decision_id(row)
    return row


def main() -> int:
    args = parse_args()
    rows: list[dict[str, str]] = []
    for path in args.inputs:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for raw in csv.DictReader(handle, delimiter=delimiter_for(path)):
                rows.append(normalize_row(raw, path))

    rows.sort(
        key=lambda row: (
            row["decision_type"],
            row["subject_key"],
            row["field_name"],
            row["decision_id"],
        )
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DECISION_COLUMNS, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)

    summary = validate_decision_ledger(args.output)
    print(f"wrote {summary.rows} decisions to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
