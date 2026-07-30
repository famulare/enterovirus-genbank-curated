"""Compare a rebuild against the shipped release.

Two comparison shapes, and the difference is not cosmetic. The source layer is compared by **file
hash**, because every one of its artifacts is fully regenerated. The metadata transport is compared
**cell by cell**, because it fills thirteen of twenty-six canonical columns and its bytes are
legitimately not the release's bytes.

## Why the build runs in a child process

`--guard-inputs` on a `parity-*` verb used to install the audit hook in the *same* process that then
read `final/` to compare. That made the guard structurally unable to catch the thing it exists to
catch here: a build that read the comparison target would look identical to the comparison itself.
The build now runs as a guarded child and the comparison happens in the unguarded parent, so
`sandbox`'s refusal to read `final/` applies to the build and only to the build.

`sandbox.ESCAPE_EVENTS` refuses `subprocess`, so the parent cannot be guarded — it is the process
doing the spawning and the release reading. That is the intended arrangement, not a gap.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.build import build_metadata_layer, build_source_layer
from enterovirus_genbank_curated.contracts import ContractError, sha256_file
from enterovirus_genbank_curated.derive.metadata import (
    CANONICAL_COLUMNS,
    SEQUENCE_RESCUED_INCLUSIONS,
    UNDECLARED_EXCLUSIONS,
)
from enterovirus_genbank_curated.export.metadata import (
    TRANSPORT_COLUMN_ORDER,
    read_metadata_transport,
)
from enterovirus_genbank_curated.genbank.parse import TABLE_COLUMNS
from enterovirus_genbank_curated.oracle.release import (
    RELEASE_FILE_MANIFEST_PATH,
    load_release_file_manifest,
    read_tsv_gz,
)

SHIPPED_SOURCE_DIR = "final/source"
SHIPPED_CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"
VERSION_COLUMN = "version"
GUARD_PASS_MARKER = "undeclared-input guard: PASS"


def run_guarded_build(repository_root: Path, verb: str, output_dir: Path) -> None:
    """Run one build verb in a guarded child, and require the guard to have passed.

    Checking the marker rather than only the exit status matters: a build that never installed the
    guard also exits 0, and this function exists to establish that the guard was in force while the
    artifacts under comparison were produced.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "enterovirus_genbank_curated.cli", verb,
            "--repository-root", str(repository_root),
            "--output", str(output_dir),
            "--guard-inputs",
        ],
        capture_output=True, text=True, cwd=repository_root, timeout=1800, check=False,
    )
    combined = result.stdout + result.stderr
    if result.returncode != 0:
        raise ContractError(f"guarded `evgc {verb}` failed:\n{combined}")
    if GUARD_PASS_MARKER not in result.stdout:
        raise ContractError(
            f"guarded `evgc {verb}` exited 0 without reporting {GUARD_PASS_MARKER!r}, so the "
            f"artifacts it produced are not covered by the guard:\n{combined}"
        )


def _release_declared_hashes(repository_root: Path) -> dict[str, str]:
    """`file_bytes` hashes the release itself declares, for every `source/` artifact."""
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    return {
        path: sha256
        for path, (scope, sha256) in manifest.items()
        if path.startswith("source/") and scope == "file_bytes"
    }


def compare_source_to_release(repository_root: Path, built_dir: Path) -> dict[str, str]:
    """Compare every regenerated artifact against the hash the RELEASE MANIFEST declares.

    Comparing against the on-disk copy in `final/source/` would be self-certifying: a build that
    had overwritten the release would then be compared against itself and pass. The authority is
    `final/audit/release_file_manifest.tsv`, which is covered by `evgc validate-contracts`. The
    on-disk copy is checked too, so a tampered release is reported separately from a bad build.

    Covers the twelve TSVs and the twelve Parquet files — every `source/` artifact the manifest
    declares at `file_bytes` scope. Only `genbank_source.duckdb` is excluded, because DuckDB file
    bytes are genuinely not reproducible; the manifest records a `logical_content` hash for it.
    """
    declared = _release_declared_hashes(repository_root)
    if not declared:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} declares no byte-hashed source/ artifacts; there is "
            f"nothing to compare against"
        )

    results: dict[str, str] = {}
    for relative, expected in sorted(declared.items()):
        built = built_dir / Path(relative).relative_to("source")
        shipped = repository_root / SHIPPED_SOURCE_DIR / Path(relative).relative_to("source")
        if not built.is_file():
            results[relative] = f"not produced by the build: {built}"
            continue
        built_hash = sha256_file(built)
        if built_hash != expected:
            results[relative] = f"rebuilt sha256 {built_hash} != manifest {expected}"
            continue
        if not shipped.is_file():
            results[relative] = f"shipped artifact missing: {shipped}"
            continue
        shipped_hash = sha256_file(shipped)
        if shipped_hash != expected:
            results[relative] = (
                f"shipped artifact does not match its own manifest ({shipped_hash} != {expected}) "
                f"— the release on disk has been altered"
            )
            continue
        results[relative] = "match"
    return results


def verify_source_parity(repository_root: Path, *, guarded: bool = False) -> dict[str, str]:
    """Rebuild the source layer and check it against the release's own manifest."""
    declared = _release_declared_hashes(repository_root)
    expected_tables = {f"source/normalized_tsv/{name}.tsv.gz" for name in TABLE_COLUMNS}
    missing = sorted(expected_tables - set(declared))
    if missing:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} does not declare byte hashes for {missing}; parity "
            f"would silently skip them"
        )

    with tempfile.TemporaryDirectory(prefix="evgc-parity-") as scratch:
        if guarded:
            run_guarded_build(repository_root, "build-source", Path(scratch))
        else:
            build_source_layer(repository_root, Path(scratch), relational=True)
        results = compare_source_to_release(repository_root, Path(scratch))

    mismatches = {k: v for k, v in results.items() if v != "match"}
    if mismatches:
        detail = "; ".join(f"{k}: {v}" for k, v in sorted(mismatches.items()))
        raise ContractError(f"source layer does not reproduce the shipped release — {detail}")
    return results


@dataclass(frozen=True)
class MetadataParityResult:
    compared_rows: int
    compared_columns: tuple[str, ...]
    shipped_rows: int
    built_rows: int
    absent_from_build: tuple[str, ...]
    absent_from_release: tuple[str, ...]


def compare_metadata_to_release(
    repository_root: Path, rows: list[dict[str, str]]
) -> MetadataParityResult:
    """Compare the transport to the shipped canonical table cell by cell.

    Not a file hash, and it cannot be one: the transport fills thirteen of twenty-six columns, so
    its bytes are legitimately not the release's bytes. What is being claimed is narrower and
    checkable — every cell this stage produces equals the shipped cell, for every record both
    agree belongs in the carve.

    The row-set difference is compared against the two declared residual sets rather than merely
    reported. A record drifting in or out of the carve is a scientific change, and
    `docs/pipeline.md`'s review stop conditions say that fails rather than gets absorbed.
    """
    header, shipped_rows = read_tsv_gz(repository_root / SHIPPED_CANONICAL_METADATA)
    if tuple(header) != CANONICAL_COLUMNS:
        raise ContractError(
            f"{SHIPPED_CANONICAL_METADATA} columns are not the declared canonical schema; "
            f"release header is {header}"
        )
    index = {column: position for position, column in enumerate(header)}
    shipped = {row[index[VERSION_COLUMN]]: row for row in shipped_rows}
    if len(shipped) != len(shipped_rows):
        raise ContractError(f"{SHIPPED_CANONICAL_METADATA} has duplicate {VERSION_COLUMN} values")
    built = {row[VERSION_COLUMN]: row for row in rows}
    if len(built) != len(rows):
        raise ContractError(f"the transport produced duplicate {VERSION_COLUMN} values")

    absent_from_build = frozenset(shipped) - frozenset(built)
    absent_from_release = frozenset(built) - frozenset(shipped)
    if absent_from_build != SEQUENCE_RESCUED_INCLUSIONS:
        raise ContractError(
            "the canonical row-set gap is not the declared one: expected "
            f"{sorted(SEQUENCE_RESCUED_INCLUSIONS)}, got {sorted(absent_from_build)}"
        )
    if absent_from_release != UNDECLARED_EXCLUSIONS:
        raise ContractError(
            "the transport includes records the release excludes, beyond the declared set: "
            f"expected {sorted(UNDECLARED_EXCLUSIONS)}, got {sorted(absent_from_release)}"
        )

    # Row order, not only row membership. Both tables are the version-sorted corpus restricted to a
    # carve, so the shared records must appear in the same sequence — a table that agrees cell for
    # cell but shuffles rows would still not be the release table.
    shared_built = [row[VERSION_COLUMN] for row in rows if row[VERSION_COLUMN] in shipped]
    shared_shipped = [v for v in shipped if v in built]
    if shared_built != shared_shipped:
        raise ContractError(
            "the transport emits the shared records in a different order than the shipped release"
        )

    differences: list[str] = []
    for version in sorted(frozenset(built) & frozenset(shipped)):
        release_row = shipped[version]
        for column in TRANSPORT_COLUMN_ORDER:
            expected = release_row[index[column]]
            actual = built[version][column]
            if actual != expected:
                differences.append(f"{version}.{column}: built {actual!r} != shipped {expected!r}")
    if differences:
        shown = "; ".join(differences[:10])
        raise ContractError(
            f"{len(differences)} transported cells disagree with the shipped release — {shown}"
        )

    return MetadataParityResult(
        compared_rows=len(frozenset(built) & frozenset(shipped)),
        compared_columns=TRANSPORT_COLUMN_ORDER,
        shipped_rows=len(shipped),
        built_rows=len(built),
        absent_from_build=tuple(sorted(absent_from_build)),
        absent_from_release=tuple(sorted(absent_from_release)),
    )


def verify_metadata_parity(
    repository_root: Path, *, guarded: bool = False
) -> MetadataParityResult:
    """Rebuild the metadata transport and check it against the shipped release."""
    with tempfile.TemporaryDirectory(prefix="evgc-metadata-parity-") as scratch:
        if guarded:
            run_guarded_build(repository_root, "build-metadata", Path(scratch))
            rows = read_metadata_transport(Path(scratch))
        else:
            rows = build_metadata_layer(repository_root, Path(scratch)).rows
        return compare_metadata_to_release(repository_root, rows)
