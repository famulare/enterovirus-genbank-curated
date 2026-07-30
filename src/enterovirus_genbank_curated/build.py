"""Pipeline stages that regenerate release artifacts from `raw/`.

Two stages exist so far, and they are reproducible to different depths.

The **source layer** is complete: `raw/sequence.gb.zip` in, twelve normalized relations out,
byte-identical to the shipped release, with no registry, no curated master, no network, and no path
outside the clone.

The **canonical metadata transport** is partial by construction and says so. It carves the canonical
row set and fills the thirteen columns whose value is a source value; the other thirteen need the
curated master or a sequence-comparison stage that does not exist here yet. See
`derive/metadata.py`.

Nothing here reads `final/`. The comparisons against the shipped release live in
`oracle/parity.py`, and `sandbox.install_input_guard` refuses a `final/` read outright, so that
separation is a property of the runtime rather than of this docstring.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    DECISIONS_LEDGER_PATH,
    DECISIONS_SCHEMA_PATH,
    PARITY_SPEC_PATH,
    ContractError,
    load_decision_contract,
    validate_decision_ledger,
    validate_parity_spec,
    verify_raw_input,
)
from enterovirus_genbank_curated.derive.metadata import (
    load_excluded_accessions,
    transport_metadata,
)
from enterovirus_genbank_curated.export.metadata import write_metadata_transport
from enterovirus_genbank_curated.export.source import (
    write_source_relational,
    write_source_tsv,
)
from enterovirus_genbank_curated.genbank.parse import parse_source_tables

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


def parse_authenticated_source(repository_root: Path) -> dict[str, list[dict[str, str]]]:
    """Parse the frozen archive and refuse a corpus that is not the size the contract declares.

    The archive is hash-authenticated, so its record count is a known quantity. Not checking it
    meant a non-GenBank or empty input produced twelve header-only tables and exited 0.
    """
    spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
    expected_records = spec["raw_input"]["record_count"]

    with extracted_flat_file(repository_root) as flat_file:
        tables = parse_source_tables(flat_file)

    actual_records = len(tables["records"])
    if actual_records != expected_records:
        raise ContractError(
            f"parsed {actual_records} records but the authenticated archive declares "
            f"{expected_records}"
        )
    return tables


def build_source_layer(
    repository_root: Path, output_dir: Path, *, relational: bool = True
) -> SourceBuildResult:
    """Regenerate `source/` from the frozen archive alone."""
    reject_immutable_output(repository_root, output_dir)
    tables = parse_authenticated_source(repository_root)
    counts = write_source_tsv(output_dir, tables)
    if relational:
        write_source_relational(output_dir)
    return SourceBuildResult(row_counts=counts, output_dir=output_dir)

@dataclass(frozen=True)
class MetadataBuildResult:
    rows: list[dict[str, str]]
    row_counts: dict[str, int]
    output_dir: Path


def build_metadata_layer(repository_root: Path, output_dir: Path) -> MetadataBuildResult:
    """Carve the canonical row set and transport every transportable column into it.

    The ledger is validated before it is used, not after. `load_excluded_accessions` reads three
    columns and would happily accept a ledger with a duplicate active assertion or an out-of-range
    status, which is exactly the input that should stop a build rather than shape one.
    """
    reject_immutable_output(repository_root, output_dir)
    contract = load_decision_contract(repository_root / DECISIONS_SCHEMA_PATH)
    ledger_path = repository_root / DECISIONS_LEDGER_PATH
    validate_decision_ledger(ledger_path, contract)
    excluded = load_excluded_accessions(ledger_path)

    tables = parse_authenticated_source(repository_root)
    transport = transport_metadata(tables, excluded)
    row_counts = {
        "source_records": len(tables["records"]),
        "transported": len(transport.rows),
        "excluded_by_ledger": transport.excluded_by_ledger,
        "excluded_as_non_enterovirus": transport.excluded_as_non_enterovirus,
    }
    write_metadata_transport(output_dir, transport.rows, row_counts)
    return MetadataBuildResult(
        rows=transport.rows, row_counts=row_counts, output_dir=output_dir
    )


