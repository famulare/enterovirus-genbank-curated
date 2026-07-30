#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12,<3.14"
# dependencies = ["numpy==2.5.1"]
# ///
"""Build the site's data artifacts from `final/`.

    uv run site/pipeline/cli.py build     # regenerate site/data/ and the manifest
    uv run site/pipeline/cli.py selftest  # check the divergence metric and the frames

`site/data/` is generated, not committed: ci.yml builds it on every pull request and
pages.yml builds what it publishes. Nothing here is checked into the repository, so
there is no `check` subcommand and no stale-artifact failure mode to guard against.

Dependencies are declared inline (PEP 723) rather than in the project's
`pyproject.toml`, so this runs from a fresh clone without installing the package
being rewritten alongside it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contract  # noqa: E402
import frame  # noqa: E402
import manifest  # noqa: E402
import panels  # noqa: E402
import records as records_module  # noqa: E402
import summary  # noqa: E402
import traits  # noqa: E402
import trees  # noqa: E402


def write_json(name: str, payload: dict, *, compact: bool = False) -> str:
    path = contract.DATA_OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    # Figure payloads are long integer arrays that no one reads by hand, so they are
    # written compactly; the small descriptive artifacts stay diff-friendly.
    text = (
        json.dumps(payload, separators=(",", ":"), sort_keys=True)
        if compact
        else json.dumps(payload, indent=2, sort_keys=True)
    )
    path.write_text(text + "\n")
    return name


def command_build(_args) -> int:
    all_records, by_accession = traits.build_records()
    print(f"read {len(all_records):,} canonical records")

    artifacts = [
        write_json("records.json", records_module.build(all_records), compact=True),
    ]

    record_index = records_module.index_by_accession(all_records)
    coords = frame.read_region_coordinates()
    cache: dict[str, frame.Alignment] = {}
    # summary.json is written after the loop, not before it: the consensus-coverage
    # disclosure it carries is measured off the non-polio polyprotein panel, and
    # measuring it is the only way that number cannot drift from the figure.
    inflation: dict | None = None

    for selection in contract.SELECTIONS:
        name = selection["alignment"]
        if name not in cache:
            cache[name] = frame.load_alignment(name)
        alignment = cache[name]
        columns = frame.region_columns(alignment, selection, coords)
        population = panels.resolve_population(
            selection, alignment, all_records, by_accession, record_index
        )
        payload = panels.build_selection(selection, alignment, columns, population)
        artifacts.append(
            write_json(f"panels/{selection['id']}.json", payload, compact=True)
        )
        if selection["restrict"] == contract.GROUP_NPEV:
            inflation = summary.consensus_inflation(
                payload["divergence"][contract.REGION_POLYPROTEIN]
            )
        counts = {
            region: len(panel["record"]) for region, panel in payload["divergence"].items()
        }
        print(f"  {selection['id']:5s} {counts}")

        forest = trees.build_selection(selection, alignment, columns, population)
        artifacts.append(write_json(f"trees/{selection['id']}.json", forest, compact=True))
        tips = {
            region: len(tree["tip_record"]) for region, tree in forest["nucleotide"].items()
        }
        print(f"  {selection['id']:5s} tips {tips}")

    if inflation is None:
        raise RuntimeError(
            "no selection restricted to non-polio records, so the consensus-coverage "
            "disclosure could not be measured. Check contract.SELECTIONS."
        )
    artifacts.append(
        write_json("summary.json", summary.build(all_records, by_accession, inflation))
    )

    written = manifest.write(manifest.artifact_hashes(artifacts))
    total = 0
    for name in artifacts:
        size = (contract.DATA_OUT / name).stat().st_size
        total += size
        print(f"wrote site/data/{name} ({size / 1024:.1f} KiB)")
    print(f"total {total / 1024 / 1024:.2f} MiB · build {written['build_identity']}")
    return 0


def command_selftest(_args) -> int:
    import selftest

    return selftest.run()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="site-build", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("build", help="regenerate site/data/ from final/").set_defaults(
        run=command_build
    )
    sub.add_parser(
        "selftest", help="check the divergence metric and the coordinate frames"
    ).set_defaults(run=command_selftest)
    args = parser.parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    raise SystemExit(main())
