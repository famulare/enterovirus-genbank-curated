"""Command-line entry points for repository contract validation."""

from __future__ import annotations

import argparse
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    ContractError,
    validate_contracts,
    validate_decision_ledger,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evgc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    contracts = subparsers.add_parser(
        "validate-contracts",
        help="validate schemas and the immutable v2.1.5 parity contract",
    )
    contracts.add_argument("--repository-root", type=Path, default=Path.cwd())

    ledger = subparsers.add_parser(
        "validate-ledger",
        help="validate a human-readable curation decision ledger",
    )
    ledger.add_argument("path", type=Path, nargs="?", default=Path("registry/decisions.tsv"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "validate-contracts":
            validate_contracts(args.repository_root.resolve())
            print("repository contracts: PASS")
            return 0
        if args.command == "validate-ledger":
            summary = validate_decision_ledger(args.path)
            print(
                f"decision ledger: PASS ({summary.rows} rows, "
                f"{summary.active_rows} active)"
            )
            return 0
    except ContractError as exc:
        print(f"contract validation failed: {exc}")
        return 1
    raise AssertionError(f"unhandled command: {args.command}")
