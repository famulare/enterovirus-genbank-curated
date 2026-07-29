"""Pipeline stages that regenerate release artifacts from `raw/`.

Only the source layer exists so far. It is genuinely reproducible: `raw/sequence.gb.zip` in,
twelve normalized relations out, byte-identical to the shipped v2.1.5 release, with no registry,
no curated master, no network, and no path outside the clone.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    PARITY_SPEC_PATH,
    RELEASE_FILE_MANIFEST_PATH,
    ContractError,
    load_release_file_manifest,
    sha256_file,
    validate_parity_spec,
    verify_raw_input,
)
from enterovirus_genbank_curated.export.source import (
    write_source_relational,
    write_source_tsv,
)
from enterovirus_genbank_curated.genbank.parse import TABLE_COLUMNS, parse_source_tables

SHIPPED_SOURCE_DIR = "final/source"
IMMUTABLE_DIRS = ("final", "raw")


@dataclass(frozen=True)
class SourceBuildResult:
    row_counts: dict[str, int]
    output_dir: Path


def _same_file(a: Path, b: Path) -> bool:
    """Identity by inode, so a case-insensitive filesystem cannot disguise the same directory."""
    try:
        return a.stat().st_dev == b.stat().st_dev and a.stat().st_ino == b.stat().st_ino
    except OSError:
        return False


def reject_immutable_output(repository_root: Path, output_dir: Path) -> None:
    """Refuse to build into the shipped release.

    Path equality is not enough. On a case-insensitive filesystem `final/SOURCE` resolves to a
    different string but the *same inode* as `final/source`, so an equality check waves it through
    and the build overwrites all twelve shipped tables. Containment is checked against every
    immutable tree, by resolved path and by inode, for the target and each of its parents.
    """
    root = repository_root.resolve()
    target = output_dir.resolve()
    for name in IMMUTABLE_DIRS:
        protected = (root / name).resolve()
        if not protected.exists():
            continue
        candidates = [target, *target.parents]
        if target.is_relative_to(protected) or any(_same_file(c, protected) for c in candidates):
            raise ContractError(
                f"refusing to write into {name}/: it is an immutable parity target, not a build "
                f"destination (resolved output {target})"
            )


@contextmanager
def extracted_flat_file(repository_root: Path) -> Iterator[Path]:
    """Authenticate the frozen archive, then stream its declared member to a temp file.

    Authentication is not optional and not a warning: `verify_raw_input` re-hashes the archive and
    the member before anything is parsed, so a corrupted or substituted input fails closed here
    rather than producing a plausible-looking release.
    """
    spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
    raw = spec["raw_input"]
    verify_raw_input(repository_root, raw)

    member = raw["archive_member"]
    if Path(member).is_absolute() or ".." in Path(member).parts:
        raise ContractError(f"refusing to extract a member with a traversing name: {member!r}")

    with tempfile.TemporaryDirectory(prefix="evgc-raw-") as scratch:
        target = Path(scratch) / member
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            zipfile.ZipFile(repository_root / raw["path"]) as archive,
            archive.open(member) as source,
            target.open("wb") as sink,
        ):
            while chunk := source.read(1 << 22):
                sink.write(chunk)
        yield target


def build_source_layer(
    repository_root: Path, output_dir: Path, *, relational: bool = True
) -> SourceBuildResult:
    """Regenerate `source/` from the frozen archive alone."""
    reject_immutable_output(repository_root, output_dir)
    spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
    expected_records = spec["raw_input"]["record_count"]

    with extracted_flat_file(repository_root) as flat_file:
        tables = parse_source_tables(flat_file)

    # The archive is hash-authenticated, so its record count is a known quantity. Not checking it
    # meant a non-GenBank or empty input produced twelve header-only tables and exited 0.
    actual_records = len(tables["records"])
    if actual_records != expected_records:
        raise ContractError(
            f"parsed {actual_records} records but the authenticated archive declares "
            f"{expected_records}"
        )

    counts = write_source_tsv(output_dir, tables)
    if relational:
        write_source_relational(output_dir)
    return SourceBuildResult(row_counts=counts, output_dir=output_dir)


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


def verify_source_parity(repository_root: Path) -> dict[str, str]:
    """Rebuild the source layer into a temp dir and check it against the release's own manifest."""
    declared = _release_declared_hashes(repository_root)
    expected_tables = {f"source/normalized_tsv/{name}.tsv.gz" for name in TABLE_COLUMNS}
    missing = sorted(expected_tables - set(declared))
    if missing:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} does not declare byte hashes for {missing}; parity "
            f"would silently skip them"
        )

    with tempfile.TemporaryDirectory(prefix="evgc-parity-") as scratch:
        build_source_layer(repository_root, Path(scratch), relational=True)
        results = compare_source_to_release(repository_root, Path(scratch))

    mismatches = {k: v for k, v in results.items() if v != "match"}
    if mismatches:
        detail = "; ".join(f"{k}: {v}" for k, v in sorted(mismatches.items()))
        raise ContractError(f"source layer does not reproduce the shipped release — {detail}")
    return results
