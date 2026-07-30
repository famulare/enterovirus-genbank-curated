"""Command-line entry points for repository contract validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enterovirus_genbank_curated.build import build_source_layer, verify_source_parity
from enterovirus_genbank_curated.contracts import (
    BASELINE_RELEASE,
    DECISIONS_SCHEMA_PATH,
    ContractError,
    load_decision_contract,
    validate_contracts,
    validate_decision_ledger,
)
from enterovirus_genbank_curated.sandbox import assert_no_violations, install_input_guard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="evgc")
    subparsers = parser.add_subparsers(dest="command", required=True)

    contracts = subparsers.add_parser(
        "validate-contracts",
        help=f"validate schemas and the immutable v{BASELINE_RELEASE} parity contract",
    )
    contracts.add_argument("--repository-root", type=Path, default=Path.cwd())
    contracts.add_argument(
        "--skip-baseline-verification",
        action="store_true",
        help="only check contract shape; do not re-hash the shipped release or recount its rows",
    )

    ledger = subparsers.add_parser(
        "validate-ledger",
        help="validate a human-readable curation decision ledger",
    )
    ledger.add_argument("path", type=Path, nargs="?", default=Path("registry/decisions.tsv"))
    ledger.add_argument("--repository-root", type=Path, default=Path.cwd())

    build_source = subparsers.add_parser(
        "build-source",
        help="regenerate the normalized source layer from the frozen GenBank archive",
    )
    build_source.add_argument("--repository-root", type=Path, default=Path.cwd())
    build_source.add_argument(
        "--output", type=Path, required=True,
        help="destination directory; never write into final/, which stays immutable",
    )
    build_source.add_argument(
        "--skip-relational", action="store_true",
        help="write only the TSVs, skipping the DuckDB and Parquet exports",
    )
    build_source.add_argument(
        "--guard-inputs", action="store_true",
        help="fail on any read outside the clone, any write into final/ or raw/, or network use",
    )

    parity_source = subparsers.add_parser(
        "parity-source",
        help="rebuild the source layer and byte-compare it against the shipped release",
    )
    parity_source.add_argument("--repository-root", type=Path, default=Path.cwd())
    parity_source.add_argument(
        "--guard-inputs", action="store_true",
        help="fail on any read outside the clone, any write into final/ or raw/, or network use",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    guard = None
    try:
        if getattr(args, "guard_inputs", False):
            guard = install_input_guard(root)
        if args.command == "validate-contracts":
            validate_contracts(root, verify_baseline=not args.skip_baseline_verification)
            scope = "shape only" if args.skip_baseline_verification else "shape and shipped release"
            print(f"repository contracts: PASS ({scope})")
            return 0
        if args.command == "validate-ledger":
            contract = load_decision_contract(root / DECISIONS_SCHEMA_PATH)
            summary = validate_decision_ledger(args.path, contract)
            print(
                f"decision ledger: PASS ({summary.rows} rows, "
                f"{summary.active_rows} active)"
            )
            return 0
        if args.command == "build-source":
            output = args.output.resolve()
            result = build_source_layer(root, output, relational=not args.skip_relational)
            if guard is not None:
                assert_no_violations(guard)
            for name, count in result.row_counts.items():
                print(f"  {name:32} {count:>8}")
            print(f"source layer written to {output}")
            if guard is not None:
                print("undeclared-input guard: PASS (no read, write or connection outside scope)")
            return 0
        if args.command == "parity-source":
            results = verify_source_parity(root)
            if guard is not None:
                assert_no_violations(guard)
            print(
                f"source parity: PASS ({len(results)} artifacts match the hashes "
                f"final/audit/release_file_manifest.tsv declares)"
            )
            if guard is not None:
                print("undeclared-input guard: PASS (no read, write or connection outside scope)")
            return 0
    except ContractError as exc:
        print(f"contract validation failed: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
