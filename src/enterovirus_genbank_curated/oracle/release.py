"""Read the shipped release and check that the parity contract describes it.

Moved here from `contracts.py`, which now holds only contract *shape* validation and reads nothing
under `final/`. The split matters because `build.py` imports `contracts` — so as long as the release
readers lived there, every build transitively imported code that reads the comparison target, and
"the build does not read the release" was a claim about discipline rather than about reachability.

Without the verification in this module the parity contract would be self-certifying: a wrong hash
or a wrong row count would sit in the spec and never be contradicted by anything.
"""

from __future__ import annotations

import csv
import gzip
from pathlib import Path
from typing import Any

from enterovirus_genbank_curated.contracts import (
    PARITY_SPEC_PATH,
    ContractError,
    load_json,
    sha256_file,
    validate_contract_shape,
    validate_parity_spec,
    verify_raw_input,
)

BUILD_MANIFEST_PATH = "final/audit/build_manifest.json"
RELEASE_FILE_MANIFEST_PATH = "final/audit/release_file_manifest.tsv"

# Where each expected_counts key is measured in the shipped release. provisional_rows is not a
# table row count; it is derived from curation_status and handled separately.
COUNT_SOURCES = {
    "source_records": "final/audit/record_disposition.tsv.gz",
    "canonical_rows": "final/canonical/sequence_metadata.tsv.gz",
    "vouched_rows": "final/canonical/sequence_metadata_vouched.tsv.gz",
    "manual_decisions": "final/audit/manual_decisions.tsv.gz",
    "rules": "final/audit/rules.tsv.gz",
}
CURATION_STATUS_COLUMN = "curation_status"
VOUCHED_STATUS = "vouched"
PROVISIONAL_STATUS = "provisional"


def read_tsv_gz(path: Path) -> tuple[list[str], list[list[str]]]:
    """Read a shipped TSV.gz with the same quoting the release writer used.

    The release tables are written by `csv.DictWriter` at its default QUOTE_MINIMAL, so free-text
    columns containing tabs or newlines are quoted. They must be read the same way: reading them
    as plain tab-delimited text counts continuation lines as rows. `comments.tsv.gz` is the live
    example — 18,476 real rows across 27,038 physical lines.

    `registry/decisions.tsv` uses the same standard quoting, but additionally guarantees that
    nothing ever *needs* quoting — see `contracts.validate_decision_ledger`.
    """
    try:
        with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            rows = list(reader)
    except OSError as exc:
        raise ContractError(f"cannot read {path}: {exc}") from exc
    if not rows:
        raise ContractError(f"{path} is empty")
    return rows[0], rows[1:]


def load_release_file_manifest(path: Path) -> dict[str, tuple[str, str]]:
    """Read the release's own file manifest as {path relative to final/: (hash_scope, sha256)}.

    Written by the same release writer as the tables, so QUOTE_MINIMAL — see `read_tsv_gz`.
    """
    try:
        handle = path.open("r", encoding="utf-8", newline="")
    except OSError as exc:
        raise ContractError(f"cannot read release file manifest {path}: {exc}") from exc
    with handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
        required = {"path", "hash_scope", "sha256"}
        if not required <= set(reader.fieldnames or ()):
            raise ContractError(f"{path} must declare columns {sorted(required)}")
        entries: dict[str, tuple[str, str]] = {}
        for row in reader:
            if row["path"] in entries:
                raise ContractError(f"{path}: duplicate entry for {row['path']}")
            entries[row["path"]] = (row["hash_scope"], row["sha256"])
    if not entries:
        raise ContractError(f"{path} declares no files")
    return entries


def verify_expected_artifacts(repository_root: Path, artifacts: list[dict[str, Any]]) -> None:
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    for artifact in artifacts:
        artifact_path = artifact["path"]
        manifest_key = artifact_path.removeprefix("final/")
        declared = manifest.get(manifest_key)
        if declared is None:
            raise ContractError(f"{artifact_path} is not declared in {RELEASE_FILE_MANIFEST_PATH}")
        manifest_scope, manifest_sha = declared
        if manifest_scope != artifact["hash_scope"]:
            raise ContractError(
                f"{artifact_path} hash_scope {artifact['hash_scope']!r} disagrees with the "
                f"release manifest ({manifest_scope!r})"
            )
        if manifest_sha != artifact["sha256"]:
            raise ContractError(
                f"{artifact_path} sha256 disagrees with the release manifest: parity "
                f"{artifact['sha256']}, manifest {manifest_sha}"
            )

        target = repository_root / artifact_path
        if not target.is_file():
            raise ContractError(f"declared parity artifact is missing: {artifact_path}")
        if artifact["hash_scope"] == "file_bytes":
            actual = sha256_file(target)
            if actual != artifact["sha256"]:
                raise ContractError(
                    f"{artifact_path} sha256 {actual} does not match the parity contract "
                    f"{artifact['sha256']}"
                )


def verify_expected_counts(repository_root: Path, counts: dict[str, int]) -> None:
    for key, relative in COUNT_SOURCES.items():
        path = repository_root / relative
        if not path.is_file():
            raise ContractError(f"cannot count {key}: missing {relative}")
        _, rows = read_tsv_gz(path)
        if len(rows) != counts[key]:
            raise ContractError(
                f"{key}: {relative} has {len(rows)} rows, parity contract declares {counts[key]}"
            )

    canonical = repository_root / COUNT_SOURCES["canonical_rows"]
    header, rows = read_tsv_gz(canonical)
    if CURATION_STATUS_COLUMN not in header:
        raise ContractError(f"{canonical} has no {CURATION_STATUS_COLUMN} column")
    index = header.index(CURATION_STATUS_COLUMN)
    tally: dict[str, int] = {}
    for row in rows:
        if len(row) != len(header):
            raise ContractError(f"{canonical} has a row with {len(row)} of {len(header)} fields")
        tally[row[index]] = tally.get(row[index], 0) + 1
    unknown = sorted(set(tally) - {VOUCHED_STATUS, PROVISIONAL_STATUS})
    if unknown:
        raise ContractError(f"{canonical} has undeclared {CURATION_STATUS_COLUMN}: {unknown}")
    for status, key in ((VOUCHED_STATUS, "vouched_rows"), (PROVISIONAL_STATUS, "provisional_rows")):
        if tally.get(status, 0) != counts[key]:
            raise ContractError(
                f"{key}: canonical metadata has {tally.get(status, 0)} {status} rows, parity "
                f"contract declares {counts[key]}"
            )


def verify_build_manifest(repository_root: Path, spec: dict[str, Any]) -> None:
    manifest = load_json(repository_root / BUILD_MANIFEST_PATH)
    checks = (
        ("git_sha", spec["source_release_commit"], "source_release_commit"),
        ("schema_version", spec["source_schema_version"], "source_schema_version"),
        ("source_genbank_sha256", spec["raw_input"]["uncompressed_sha256"], "raw uncompressed"),
    )
    for field, expected, label in checks:
        actual = manifest.get(field)
        if actual != expected:
            raise ContractError(
                f"{BUILD_MANIFEST_PATH} {field}={actual!r} does not match parity {label} "
                f"{expected!r}"
            )
    if manifest.get("git_tree_clean") is not True:
        raise ContractError(f"{BUILD_MANIFEST_PATH} was not built from a clean tree")


def verify_release_baseline(repository_root: Path, spec: dict[str, Any]) -> None:
    """Check that the parity contract describes the release actually shipped in this repository."""
    verify_build_manifest(repository_root, spec)
    verify_raw_input(repository_root, spec["raw_input"])
    verify_expected_artifacts(repository_root, spec["expected_artifacts"])
    verify_expected_counts(repository_root, spec["expected_counts"])


def validate_contracts(repository_root: Path, *, verify_baseline: bool = True) -> None:
    """Validate contract shape, then that the contracts describe the shipped release.

    The composed verb lives here rather than in `contracts.py` because its second half reads
    `final/`. `contracts.validate_contract_shape` is the half that does not.
    """
    validate_contract_shape(repository_root)
    if verify_baseline:
        spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
        verify_release_baseline(repository_root, spec)
