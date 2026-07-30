#!/usr/bin/env python3
"""Migrate the locked VDPV/wild reconciliation allowlist into `registry/decisions.tsv`.

A one-time historical tool, like `migrate_legacy_registries.py`, and not a pipeline stage.

## What is being migrated, and why it is not a pending delta

`reconcile_sequence_classification` computes `classification_reconciled` from the text
classification and the sequence tier, and then lets one hand-maintained allowlist —
`vdpv_wild_reconciliation.csv` in the private working tree — take precedence over the computed
call. That allowlist is 243 rows and is the last input to `poliovirus_classification` with no
counterpart in this repository, which made it a hard blocker for ever rebuilding that column:
243 records would have been permanently unreachable no matter how good the rules got.

Every one of the 243 already agrees with the shipped `poliovirus_classification`. So this captures
curation that is *already applied*, not an assertion the release contradicts — the opposite of the
D2 situation, where a ledger row existed with no counterpart in the artifact the pipeline reads.

## Choices worth stating

`decision_type` is `manual_override` and `field_name` is `classification`, matching the 1,788
classification overrides already in the ledger, rather than a new `vdpv_wild_reconciliation` type.
A new type would be the more faithful 1:1-with-source-artifact pattern, but `decision_type` has no
enum (backlog B19) and `final/dictionaries/controlled_vocabularies.tsv` enumerates exactly ten
values for it. That vocabulary describes the shipped 2.4.1 release and is immutable, so inventing an
eleventh value here would put the ledger outside a controlled vocabulary the release publishes.
`source_artifact` carries the origin instead, which is what it is for.

Reused from `migrate_legacy_registries.py` rather than restated: `normalize_for_plain_tsv` (the
ASCII-double-quote conversion that keeps the ledger safe for naive tab-splitting — 154 of these rows
need it) and `assign_ids` (the content-stable `D-<12 hex of sha256 over ID_COLUMNS>` scheme). Two
copies of an id scheme is how `migrate_decisions.py` came to be deleted as cruft.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from migrate_legacy_registries import (  # noqa: E402
    assign_ids,
    normalize_for_plain_tsv,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from enterovirus_genbank_curated.contracts import (  # noqa: E402
    ACTIVE_STATUS,
    DECISION_COLUMNS,
    DECISIONS_LEDGER_PATH,
    DECISIONS_SCHEMA_PATH,
    LEDGER_SORT_COLUMNS,
    ContractError,
    load_decision_contract,
    validate_decision_ledger,
)

SOURCE_NAME = "vdpv_wild_reconciliation.csv"
SOURCE_COLUMNS = ("accession", "reconciled_classification", "reason", "strain", "paper")
EXPECTED_SOURCE_ROWS = 243
DECISION_TYPE = "manual_override"
FIELD_NAME = "classification"
CONFIRMED_BY = "Mike"


def read_allowlist(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != SOURCE_COLUMNS:
            raise ContractError(
                f"{path} columns are {reader.fieldnames}, expected {SOURCE_COLUMNS}"
            )
        rows = list(reader)
    # The private tree is a live working directory. A source that has moved must fail here, at the
    # point of divergence, rather than quietly writing a ledger the shipped release never matched.
    if len(rows) != EXPECTED_SOURCE_ROWS:
        raise ContractError(
            f"{path} has {len(rows)} rows, expected {EXPECTED_SOURCE_ROWS}; the private allowlist "
            f"has moved since this migration was written and the new rows need adjudicating"
        )
    accessions = [r["accession"] for r in rows]
    if len(set(accessions)) != len(accessions):
        raise ContractError(f"{path} has duplicate accessions")
    return rows


def to_decisions(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    decisions: list[dict[str, str]] = []
    for row in rows:
        accession = row["accession"]
        where = f"{SOURCE_NAME}:{accession}"
        reason = normalize_for_plain_tsv(
            f"Reconciliation allowlist ({row['reason']}). {row['paper']}".strip(), where=where
        )
        decisions.append(
            {
                "decision_id": "",
                "decision_type": DECISION_TYPE,
                "subject_key": accession,
                "accession": accession,
                "field_name": FIELD_NAME,
                "new_value": normalize_for_plain_tsv(
                    row["reconciled_classification"], where=where
                ),
                "reason": reason,
                "evidence_reference": "",
                "confirmed_by": CONFIRMED_BY,
                "source_artifact": SOURCE_NAME,
                "status": ACTIVE_STATUS,
                "effective_from": "",
                "effective_through": "",
                "notes": normalize_for_plain_tsv(f"strain={row['strain']}", where=where),
            }
        )
    return assign_ids(decisions)


def merge_into_ledger(ledger_path: Path, additions: list[dict[str, str]]) -> int:
    with ledger_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        existing = list(reader)

    seen_ids = {row["decision_id"] for row in existing}
    # A colliding 12-hex digest would be disambiguated with a `-2` suffix, which the decisions
    # schema's own `^D-[0-9a-f]{12,64}$` pattern rejects (backlog B20). Stop rather than emit an id
    # the contract refuses.
    collisions = sorted(seen_ids & {row["decision_id"] for row in additions})
    if collisions:
        raise ContractError(f"decision_id collides with an existing row: {collisions}")

    active = {
        (row["subject_key"], row["field_name"])
        for row in existing
        if row["status"] == ACTIVE_STATUS
    }
    conflicts = sorted(
        f"{row['subject_key']}/{row['field_name']}"
        for row in additions
        if (row["subject_key"], row["field_name"]) in active
    )
    if conflicts:
        raise ContractError(
            f"{len(conflicts)} additions would be a second active assertion for a subject and "
            f"field the ledger already governs: {conflicts[:10]}"
        )

    merged = sorted(
        existing + additions, key=lambda row: tuple(row[c] for c in LEDGER_SORT_COLUMNS)
    )
    with ledger_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(DECISION_COLUMNS), delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(merged)
    return len(merged)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source",
        type=Path,
        help=f"path to the private {SOURCE_NAME} (MAD-VDPV/data/genbank/working)",
    )
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    root = args.repository_root.resolve()
    ledger = root / DECISIONS_LEDGER_PATH

    try:
        additions = to_decisions(read_allowlist(args.source))
        total = merge_into_ledger(ledger, additions)
        contract = load_decision_contract(root / DECISIONS_SCHEMA_PATH)
        summary = validate_decision_ledger(ledger, contract)
    except ContractError as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1

    print(f"added {len(additions)} rows; ledger now {total} rows ({summary.active_rows} active)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
