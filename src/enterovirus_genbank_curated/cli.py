"""Command-line entry points for repository contract validation."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from enterovirus_genbank_curated.align.runner import DEFAULT_THREADS
from enterovirus_genbank_curated.build import build_metadata_layer, build_source_layer
from enterovirus_genbank_curated.contracts import (
    BASELINE_RELEASE,
    DECISIONS_SCHEMA_PATH,
    ContractError,
    load_decision_contract,
    validate_decision_ledger,
)
from enterovirus_genbank_curated.oracle.parity import (
    verify_metadata_declines,
    verify_source_parity,
)
from enterovirus_genbank_curated.oracle.release import validate_contracts
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
        help="run the build in a guarded child process; the comparison itself reads final/ and "
             "therefore cannot be guarded",
    )

    build_metadata = subparsers.add_parser(
        "build-metadata",
        help="carve the canonical row set and transport the source-derived metadata columns",
    )
    build_metadata.add_argument("--repository-root", type=Path, default=Path.cwd())
    build_metadata.add_argument(
        "--output", type=Path, required=True,
        help="destination directory; never write into final/, which stays immutable",
    )
    build_metadata.add_argument(
        "--guard-inputs", action="store_true",
        help="fail on any read outside the clone, any write into final/ or raw/, or network use",
    )

    declines = subparsers.add_parser(
        "check-declines",
        help="rebuild the metadata layer and check its declined cells against the declared counts",
    )
    declines.add_argument("--repository-root", type=Path, default=Path.cwd())
    declines.add_argument(
        "--guard-inputs", action="store_true",
        help="run the build in a guarded child process",
    )

    alignment_population = subparsers.add_parser(
        "alignment-population",
        help="derive each alignment's row set from final metadata; needs no aligner",
    )
    alignment_population.add_argument("--repository-root", type=Path, default=Path.cwd())
    alignment_population.add_argument(
        "--artifact", action="append", dest="artifacts", metavar="NAME",
        help="restrict to one alignment; repeatable. Default: all six.",
    )

    alignment_toolchain = subparsers.add_parser(
        "alignment-toolchain",
        help="resolve the native aligners and check them against registry/toolchain.json",
    )
    alignment_toolchain.add_argument("--repository-root", type=Path, default=Path.cwd())
    alignment_toolchain.add_argument(
        "--write-declaration", action="store_true",
        help="re-stamp registry/toolchain.json from the installed environment and the lock",
    )

    alignment_verify_seeds = subparsers.add_parser(
        "alignment-verify-seeds",
        help="re-hash the committed NCR covariance-model core; needs no aligner",
    )
    alignment_verify_seeds.add_argument("--repository-root", type=Path, default=Path.cwd())

    alignment_build = subparsers.add_parser(
        "alignment-build",
        help="build alignment artifacts, strictly one at a time (needs mafft + Infernal)",
    )
    alignment_build.add_argument("--repository-root", type=Path, default=Path.cwd())
    alignment_build.add_argument(
        "--output-dir", type=Path, required=True,
        help="where to write <name>.sto.gz, <name>_aln.fasta.gz and <name>.coverage.tsv.gz",
    )
    alignment_build.add_argument(
        "--artifact", action="append", dest="artifacts", metavar="NAME",
        help="restrict to one alignment; repeatable. Default: all six.",
    )
    # No --parallel, by design: concurrent aligner processes are what exhausted memory on a real
    # machine (see align/build.py). --threads is the one knob, and its default is 1.
    alignment_build.add_argument(
        "--threads", type=int, default=DEFAULT_THREADS,
        help=f"threads per tool invocation (default {DEFAULT_THREADS})",
    )

    alignment_verify = subparsers.add_parser(
        "alignment-verify",
        help="check built alignments against metadata-derived populations; needs no aligner",
    )
    alignment_verify.add_argument("--repository-root", type=Path, default=Path.cwd())
    alignment_verify.add_argument("--output-dir", type=Path, required=True)
    alignment_verify.add_argument(
        "--artifact", action="append", dest="artifacts", metavar="NAME",
        help="restrict to one alignment; repeatable. Default: all six.",
    )

    alignment_shape = subparsers.add_parser(
        "alignment-shape",
        help="write the shape report and the declared delta against 2.4.1; needs no aligner",
    )
    alignment_shape.add_argument("--repository-root", type=Path, default=Path.cwd())
    alignment_shape.add_argument("--output-dir", type=Path, required=True)
    alignment_shape.add_argument(
        "--artifact", action="append", dest="artifacts", metavar="NAME",
        help="restrict to one alignment; repeatable. Default: all six.",
    )
    return parser


GUARD_PASS_LINE = "undeclared-input guard: PASS (no read, write or connection outside scope)"
PARITY_COMMANDS = frozenset({"parity-source", "check-declines"})


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.repository_root.resolve()
    requested_guard = getattr(args, "guard_inputs", False)
    guard = None
    try:
        # On a `parity-*` verb `--guard-inputs` guards the *child* that builds, not this process:
        # the comparison reads `final/`, which the guard refuses, and it spawns the child, which the
        # guard also refuses. Installing it here would fail every parity run outright.
        if requested_guard and args.command not in PARITY_COMMANDS:
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
                print(GUARD_PASS_LINE)
            return 0
        if args.command == "parity-source":
            results = verify_source_parity(root, guarded=requested_guard)
            print(
                f"source parity: PASS ({len(results)} artifacts match the hashes "
                f"oracle/release.py's SOURCE_LAYER_HASHES pins)"
            )
            if requested_guard:
                print(GUARD_PASS_LINE)
            return 0
        if args.command == "build-metadata":
            output = args.output.resolve()
            metadata = build_metadata_layer(root, output)
            if guard is not None:
                assert_no_violations(guard)
            for name, count in metadata.row_counts.items():
                print(f"  {name:32} {count:>8}")
            print(f"metadata transport written to {output}")
            for status, count in sorted(metadata.application_tally.items()):
                print(f"  decisions {status:28} {count:>8}")
            if guard is not None:
                print(GUARD_PASS_LINE)
            return 0
        if args.command == "check-declines":
            observed = verify_metadata_declines(root, guarded=requested_guard)
            print(
                f"declared declines: PASS ({sum(observed.values())} declined cells across "
                f"{len(observed)} canonical fields, each equal to its declared count)"
            )
            for field, count in sorted(observed.items()):
                print(f"  {field:28} {count:>8}")
            if requested_guard:
                print(GUARD_PASS_LINE)
            return 0
        if args.command == "alignment-population":
            from enterovirus_genbank_curated.align.contract import ARTIFACTS
            from enterovirus_genbank_curated.align.population import load_all_records, select

            names = args.artifacts or list(ARTIFACTS)
            unknown = [name for name in names if name not in ARTIFACTS]
            if unknown:
                raise ContractError(
                    f"unknown alignment(s) {unknown}; declared: {sorted(ARTIFACTS)}"
                )
            records = load_all_records(root)
            print(f"canonical records: {len(records)}")
            for name in names:
                pop = select(records, ARTIFACTS[name])
                tiers = pop.tier_counts()
                status = "ok" if len(pop.records) == pop.spec.expected_rows else "UNEXPECTED"
                print(
                    f"\n{name}  {len(pop.records)} rows "
                    f"(expected {pop.spec.expected_rows}: {status})"
                )
                print(f"  population sha256  {pop.digest()}")
                print(f"  tiers              backbone {tiers['backbone']}, addon {tiers['addon']}")
                all_types = pop.type_counts()
                shown = list(all_types.items())[:8]
                types = ", ".join(f"{k} {v}" for k, v in shown)
                if len(all_types) > len(shown):
                    types += f", … ({len(all_types)} types total)"
                print(f"  types              {types}")
                families = ", ".join(f"{k} {v}" for k, v in pop.family_counts().items())
                print(f"  families           {families}")
            return 0
        if args.command == "alignment-toolchain":
            import json

            from enterovirus_genbank_curated.align import toolchain as tc

            resolved = tc.resolve(root)
            print(f"platform     {resolved.platform}")
            print(f"environment  {resolved.environment}")
            print(f"prefix       {resolved.prefix}")
            for name, tool in sorted(resolved.tools.items()):
                print(
                    f"  {name:12} {tool.package:9} {tool.version:8} {tool.build:24} "
                    f"{tool.self_reported}"
                )
            if args.write_declaration:
                declaration = tc.build_declaration(root, [resolved])
                target = root / tc.TOOLCHAIN_DECLARATION
                target.write_text(
                    json.dumps(declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8"
                )
                print(f"wrote {tc.TOOLCHAIN_DECLARATION}")
            tc.assert_declared(root, resolved)
            print("alignment toolchain: PASS (matches registry/toolchain.json and pixi.lock)")
            return 0
        if args.command == "alignment-verify-seeds":
            from enterovirus_genbank_curated.align.seeds import verify_seeds

            checked = verify_seeds(root)
            print(
                f"alignment seeds: PASS ({checked} files in registry/alignment_seeds/ match "
                f"their pinned hashes and declared match-column counts)"
            )
            return 0
        if args.command == "alignment-build":
            from enterovirus_genbank_curated.align import build as align_build

            names = tuple(args.artifacts) if args.artifacts else None

            def report(stage: str, name: str, result=None) -> None:
                if stage == "load":
                    print("loading canonical records ...", flush=True)
                elif stage == "segment":
                    print("segmenting all records (one pass, shared) ...", flush=True)
                elif stage == "start":
                    print(f"building {name} ...", flush=True)
                elif stage == "done" and result is not None:
                    s = result.stitched
                    print(
                        f"  {name}: {len(s.accessions)} rows x {s.width_nt} nt "
                        f"(5'NCR {s.width_5ncr} + CDS {s.width_cds} + 3'NCR {s.width_3ncr}) "
                        f"in {result.seconds / 60:.1f} min",
                        flush=True,
                    )

            results = align_build.build_all(
                root, args.output_dir.resolve(), names=names,
                threads=args.threads, on_event=report,
            )
            print(f"alignment build: PASS ({len(results)} artifact(s) written)")
            return 0
        if args.command == "alignment-verify":
            from enterovirus_genbank_curated.validation import alignment as validate_alignment

            names = tuple(args.artifacts) if args.artifacts else None
            report = validate_alignment.verify(root, args.output_dir.resolve(), names)
            if not report.passed:
                for failure in report.failures:
                    print(f"  {failure}", file=sys.stderr)
                print(
                    f"alignment verify: FAIL ({len(report.failures)} of {report.checks} checks)",
                    file=sys.stderr,
                )
                return 1
            print(f"alignment verify: PASS ({report.checks} checks)")
            return 0
        if args.command == "alignment-shape":
            from enterovirus_genbank_curated.align import shape as align_shape

            names = tuple(args.artifacts) if args.artifacts else None
            output_dir = args.output_dir.resolve()
            report = align_shape.build_report(root, output_dir, names)
            json_path, md_path = align_shape.write_report(output_dir, report)
            print(align_shape.render(report))
            print(f"wrote {json_path.name} and {md_path.name}")
            return 0
    except ContractError as exc:
        print(f"contract validation failed: {exc}", file=sys.stderr)
        return 1
    raise AssertionError(f"unhandled command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
