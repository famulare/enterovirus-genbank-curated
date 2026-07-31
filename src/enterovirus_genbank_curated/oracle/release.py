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
from enterovirus_genbank_curated.registry.rules import validate_rule_catalog

BUILD_MANIFEST_PATH = "final/audit/build_manifest.json"
RELEASE_FILE_MANIFEST_PATH = "final/audit/release_file_manifest.tsv"

# The twenty files under `final/` that `release_file_manifest.tsv` does not declare, and cannot.
#
# Nineteen are the carved-in alignments, produced by a private pipeline whose scripts are not in
# this repository; the manifest covers only the release_v2 build outputs. The twentieth is the
# manifest itself, which cannot declare its own hash without becoming self-referential.
#
# Their sha256s are pinned in `tests/test_carried_files.py`, following the same pattern as
# `registry/legacy/`: hashes in code, so moving one takes a reviewed source edit rather than a
# data edit. All twenty are single-source — see that file's module docstring for why a second
# witness was tried and dropped.
#
# This set shrinks to empty when the alignment layer is regenerated natively: at that point every
# file here either gains a real manifest row or is dropped. Do not add to it for a file this
# repository produces — that is what the manifest is for.
CARRIED_FINAL_FILES = frozenset({
    "final/alignments/EV_unified.provenance.json",
    "final/alignments/EV_unified.sto.gz",
    "final/alignments/EV_unified_aln.fasta.gz",
    "final/alignments/NPEV_unified.provenance.json",
    "final/alignments/NPEV_unified.sto.gz",
    "final/alignments/NPEV_unified_aln.fasta.gz",
    "final/alignments/POLIO_unified.provenance.json",
    "final/alignments/POLIO_unified.sto.gz",
    "final/alignments/POLIO_unified_aln.fasta.gz",
    "final/alignments/PV1_unified.sto.gz",
    "final/alignments/PV1_unified_aln.fasta.gz",
    "final/alignments/PV2_unified.sto.gz",
    "final/alignments/PV2_unified_aln.fasta.gz",
    "final/alignments/PV3_unified.sto.gz",
    "final/alignments/PV3_unified_aln.fasta.gz",
    "final/alignments/reference_alignment_provenance.json",
    "final/alignments/reference_msa_provenance.json",
    "final/alignments/reference_region_coordinates.tsv",
    "final/alignments/unified_stockholm_provenance.json",
    RELEASE_FILE_MANIFEST_PATH,
})

# Filesystem debris that is never release content, so `verify_manifest_completeness` must not
# demand a hash for it. Narrow by name rather than a dotfile glob, because "skip anything starting
# with a dot" would also skip a real artifact that happened to be named that way, and this check
# exists to notice unhashed files.
#
# `.DS_Store` is written by macOS Finder whenever someone opens `final/` in a window. It is
# gitignored and has never been part of a release, but the completeness walk reads the filesystem
# rather than the index — it has to, since the whole point is to find files nobody declared — so the
# two disagree exactly here.
IGNORED_FINAL_NAMES = frozenset({".DS_Store"})

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


def verify_release_manifest_hashes(repository_root: Path) -> int:
    """Recompute every `file_bytes` hash `final/audit/release_file_manifest.tsv` declares.

    `verify_expected_artifacts` only ever recomputed the `file_bytes` entries named in
    `expected_artifacts`. That left the rest of the manifest's declared hashes — e.g.
    `audit/build_manifest.json`, `audit/canonical_projection_provenance.tsv.gz`,
    `audit/sequence_evidence.tsv.gz`, the four `dictionaries/*.tsv` — computed by nothing, so
    replacing any of them with the word `garbage` passed every gate (backlog B7). Recomputing all
    of them here subsumes the split rather than adding a fourth place that has to remember which
    subset it owns.

    `logical_content` entries are skipped, and deliberately: no code in this repository computes a
    logical digest, so a check here would either be a no-op or invent a definition (backlog B6).
    Returns the number of hashes actually recomputed, so a caller can assert it is not zero.
    """
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    final_root = repository_root / "final"
    checked = 0
    for relative, (scope, declared) in sorted(manifest.items()):
        if scope not in {"file_bytes", "logical_content"}:
            raise ContractError(
                f"{RELEASE_FILE_MANIFEST_PATH} declares unknown hash_scope {scope!r} "
                f"for {relative}"
            )
        target = final_root / relative
        if not target.is_file():
            raise ContractError(
                f"{RELEASE_FILE_MANIFEST_PATH} declares final/{relative}, which does not exist"
            )
        if scope != "file_bytes":
            continue
        actual = sha256_file(target)
        if actual != declared:
            raise ContractError(
                f"final/{relative} sha256 {actual} does not match the hash "
                f"{RELEASE_FILE_MANIFEST_PATH} declares ({declared})"
            )
        checked += 1
    if checked == 0:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} declared no file_bytes hashes to recompute; "
            f"a check that verifies nothing is worse than no check"
        )
    return checked


def verify_manifest_completeness(repository_root: Path) -> None:
    """Require every file under `final/` to be covered by the manifest or declared as carried.

    The gap this closes is not a wrong hash but an absent one: nineteen alignment files and the
    self-referential manifest sat in no declaration at all, so deleting one outright left every
    gate green. The check runs in both directions — an undeclared *new* file fails just as loudly
    as a missing declared one — because a one-directional completeness check is how the original
    gap survived review.

    Membership lives in code rather than beside the hashes in a data file on purpose. A path set
    that a data edit could extend would let a future build silently move a file out of scope,
    which is the shape of defect B4.
    """
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    declared = {f"final/{relative}" for relative in manifest}
    final_root = repository_root / "final"
    if not final_root.is_dir():
        raise ContractError("final/ is missing; there is no release to validate")
    present = {
        str(path.relative_to(repository_root))
        for path in final_root.rglob("*")
        if path.is_file() and path.name not in IGNORED_FINAL_NAMES
    }

    overlap = declared & CARRIED_FINAL_FILES
    if overlap:
        raise ContractError(
            f"CARRIED_FINAL_FILES names {sorted(overlap)}, which the release manifest also "
            f"declares; a file cannot be both carried and declared"
        )
    stale = CARRIED_FINAL_FILES - present
    if stale:
        raise ContractError(
            f"CARRIED_FINAL_FILES names files that do not exist: {sorted(stale)}"
        )
    uncovered = present - declared - CARRIED_FINAL_FILES
    if uncovered:
        raise ContractError(
            f"these files under final/ are covered by neither {RELEASE_FILE_MANIFEST_PATH} nor "
            f"CARRIED_FINAL_FILES: {sorted(uncovered)}. Every shipped file needs a hash "
            f"somewhere; if this one is a new release artifact it belongs in the manifest, and if "
            f"it is carried from the private pipeline it belongs in CARRIED_FINAL_FILES with its "
            f"sha256 pinned in tests/test_carried_files.py."
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
    verify_release_manifest_hashes(repository_root)
    verify_manifest_completeness(repository_root)
    verify_expected_counts(repository_root, spec["expected_counts"])


def validate_contracts(repository_root: Path, *, verify_baseline: bool = True) -> None:
    """Validate contract shape, then that the contracts describe the shipped release.

    The composed verb lives here rather than in `contracts.py` because its second half reads
    `final/`. `contracts.validate_contract_shape` is the half that does not.

    The rule catalog is validated here rather than inside `validate_contract_shape` only to avoid an
    import cycle: `registry.rules` needs `contracts`. It is shape validation and runs even under
    `--skip-baseline-verification`.
    """
    validate_contract_shape(repository_root)
    validate_rule_catalog(repository_root)
    if verify_baseline:
        spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
        verify_release_baseline(repository_root, spec)
