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

# Files under `final/` that `release_file_manifest.tsv` does not declare, and cannot.
#
# The manifest now covers exactly what `evgc build-metadata` writes (`export.release`'s
# `BUILD_ARTIFACT_RELATIVES`), because as of 2026-08-01 `final/` *is* that build's destination.
# Everything else under `final/` is carried from an earlier release and is listed here:
#
# * the nineteen carved-in alignments, produced by a private pipeline whose scripts are not in this
#   repository;
# * the source layer and the four dictionaries, whose hashes are pinned in `SOURCE_LAYER_HASHES`
#   and `DICTIONARY_HASHES` below rather than only in tests, because `parity-source` compares a
#   rebuild against them;
# * `audit/record_disposition.tsv.gz` and `audit/sequence_evidence.tsv.gz`, which are 2.4.1 audit
#   views with no successor in the new build and are *live inputs to the alignment layer*
#   (`align/shape.py`, `align/contract.py`). They are carried deliberately until the alignment
#   layer is repointed; deleting them breaks `align/`;
# * the manifest itself, which cannot declare its own hash without becoming self-referential.
#
# Their sha256s are pinned in `tests/test_carried_files.py`, following the same pattern as
# `registry/legacy/`: hashes in code, so moving one takes a reviewed source edit rather than a
# data edit. See that file's module docstring for why a second witness was tried and dropped.
#
# Do not add to it for a file this repository produces — that is what the manifest is for.
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
    "final/audit/record_disposition.tsv.gz",  # 2.4.1; still read by align/shape.py
    "final/audit/sequence_evidence.tsv.gz",
    "final/dictionaries/audit_data_dictionary.tsv",
    "final/dictionaries/canonical_data_dictionary.tsv",
    "final/dictionaries/controlled_vocabularies.tsv",
    "final/dictionaries/source_schema_dictionary.tsv",
    "final/source/genbank_source.duckdb",
    *(f"final/source/normalized_tsv/{name}.tsv.gz" for name in (
        "comments", "feature_location_parts", "feature_qualifiers", "features",
        "record_accessions", "record_keywords", "record_taxonomy", "record_xrefs",
        "records", "reference_authors", "references", "structured_comment_fields",
    )),
    *(f"final/source/parquet/{name}.parquet" for name in (
        "comments", "feature_location_parts", "feature_qualifiers", "features",
        "record_accessions", "record_keywords", "record_taxonomy", "record_xrefs",
        "records", "reference_authors", "references", "structured_comment_fields",
    )),
    # The manifest is no longer listed here: `export/release.py` writes it with a `self` row, so it
    # declares itself and would collide with the carried set's "a file cannot be both" check.
})

# The source layer's declared byte hashes, moved here from `release_file_manifest.tsv` on
# 2026-08-01 when the manifest became a description of `build-metadata`'s output alone.
#
# `parity-source` compares a rebuild against these, so they cannot live only in a test. They cannot
# live in the manifest either: the manifest is now regenerated by every metadata build, and a hash
# a build rewrites is not an oracle. Hashes in code is this repository's existing answer to that —
# moving one takes a reviewed source edit.
#
# `source/genbank_source.duckdb` is absent on purpose: DuckDB file bytes are not reproducible. The
# retired manifest carried a `logical_content` hash for it
# (5d90c5b2f856f12a1b7133460f79f543d6d2c39aae77272d0ae53b504010dbfc) that no code in this
# repository ever computed, so recording it here would be recording a number nothing checks.
SOURCE_LAYER_HASHES = {
    "source/normalized_tsv/comments.tsv.gz":
        "92b1b5a1331e71a254f94fbd1417f1e1a763b34446d84811407b63dcf7af8c95",
    "source/normalized_tsv/feature_location_parts.tsv.gz":
        "e5394a96dd20dfa3e174d2aae1bc5e060c2a6e43c23dd86763c1298c7711ee7b",
    "source/normalized_tsv/feature_qualifiers.tsv.gz":
        "55bffaefa54d417393750f0adbb187ae6e73aefc89ca81b7946f0fdbd9354a03",
    "source/normalized_tsv/features.tsv.gz":
        "e9960328759935ba1b3e0ad5aad968190be944b9d1d2337bf5a2ee113d1fa707",
    "source/normalized_tsv/record_accessions.tsv.gz":
        "3a59b4b566027b48ae443b328dad64283c50b9d3b13ec53d2b1ef08fc4ab182d",
    "source/normalized_tsv/record_keywords.tsv.gz":
        "57fb5efd58418adcb56e26a4678d9e1851e2bcb25b08e036885f4544250b9831",
    "source/normalized_tsv/record_taxonomy.tsv.gz":
        "2da64e6af64b6aec0582b7ac7118df795f4e71f78b73f08a6ac17686de19f9b9",
    "source/normalized_tsv/record_xrefs.tsv.gz":
        "56d88f48f32f03e292caf9b2de089abc179e60e777edfb1f7d218f928aac955c",
    "source/normalized_tsv/records.tsv.gz":
        "e9f0dac657c3c9daab4d7205c8e82022630e4db9e6a35824fc7df974bfd43b92",
    "source/normalized_tsv/reference_authors.tsv.gz":
        "913f8f4feb0352dfbb6356ae1c2c38db49c6d334927cd86378c955e0df69b092",
    "source/normalized_tsv/references.tsv.gz":
        "5cee850ba48e872a19ea76207fb6f58820a5393f6dea83bfa9c59b16cc474f9c",
    "source/normalized_tsv/structured_comment_fields.tsv.gz":
        "8ee441bf2c5561e7420e826a63dc09487afe6649df94c41f1655982e760bc490",
    "source/parquet/comments.parquet":
        "d15a6c707ae6756cd7253ba450e90eaa0f39c127997bc51da0bcfdb5ac251045",
    "source/parquet/feature_location_parts.parquet":
        "528b7a81a590f9305feafa9979f056083260d56a18bbd8a18cfff8343b38c58c",
    "source/parquet/feature_qualifiers.parquet":
        "86ae6efb1e9856fb569edc5aada955de212bf23d0cd78c87143e6a4dc0e933a0",
    "source/parquet/features.parquet":
        "b2f469f6e505f9bc77856e8a55796171e5d09beb78173ca73f1fa0f6c000e228",
    "source/parquet/record_accessions.parquet":
        "4a7dd0d82f0b67b719eca368dad1d547244d7fea89559bef7223fc5ce0ccfd22",
    "source/parquet/record_keywords.parquet":
        "bed7f82953244dfd722ca08b5fb693d616643e9319b3976b3d51fa58706fc29e",
    "source/parquet/record_taxonomy.parquet":
        "d14235a6b8ab6aec9d0c907b80407cac49041f364328f47eb6fa55d36bfd9720",
    "source/parquet/record_xrefs.parquet":
        "8633ca8483966d7378cea9841580edf2575df54552880963c3bb9a5c4a2434d7",
    "source/parquet/records.parquet":
        "ff4fc93dfd62522064aee29415c7b6d6bd6a35d22f7981dca376b36ad1d07704",
    "source/parquet/reference_authors.parquet":
        "f455df9d385da3b1600320d93b3999c2442e93da07993ea42a6e2e194f7db29a",
    "source/parquet/references.parquet":
        "0ea91a27cdc397fbdf084fb8d3d1633fd5c83e324452f321776532c86c13a146",
    "source/parquet/structured_comment_fields.parquet":
        "e2607a616cf9e5231d1946214d558f4e38b265ebdb35f2664be79aabd32b0c32",
}

# Same provenance as `SOURCE_LAYER_HASHES`, for the four carried dictionaries. Separate because
# nothing rebuilds them: these are checked, not compared against a rebuild.
DICTIONARY_HASHES = {
    "dictionaries/audit_data_dictionary.tsv":
        "222ef799baa1ae7f292cc652237dd1fc9e474199eb8e8d2a76f120a33d0c2098",
    "dictionaries/canonical_data_dictionary.tsv":
        "8fc475c7ac7482e7602339fb0257ce95a4db9e9fee164570fb9903750651df70",
    "dictionaries/controlled_vocabularies.tsv":
        "7fb35d08de7796793456c634f343eaa7f55823302052a3940b4bdc9efaeb8d4a",
    "dictionaries/source_schema_dictionary.tsv":
        "e946d0ea4e77743338195052d8823dab7551e26214f5ecc5302a60b7a99fde1b",
}

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


def verify_release_manifest_hashes(repository_root: Path) -> int:
    """Recompute every `file_bytes` hash `final/audit/release_file_manifest.tsv` declares.

    The retired `verify_expected_artifacts` only ever recomputed the `file_bytes` entries named in
    the parity spec's `expected_artifacts`. That left the rest of the manifest's declared hashes
    computed by nothing, so replacing any of them with the word `garbage` passed every gate
    (backlog B7). Recomputing all of them here subsumes the split rather than adding a fourth place
    that has to remember which subset it owns — and it is why the manifest shrinking to the build's
    own twelve artifacts did not reopen the hole: the files that left it gained pins in code
    (`SOURCE_LAYER_HASHES`, `DICTIONARY_HASHES`, `tests/test_carried_files.py`) rather than losing
    a hash.

    `logical_content` entries are skipped, and deliberately: no code in this repository computes a
    logical digest, so a check here would either be a no-op or invent a definition (backlog B6).
    Returns the number of hashes actually recomputed, so a caller can assert it is not zero.
    """
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    final_root = repository_root / "final"
    checked = 0
    for relative, (scope, declared) in sorted(manifest.items()):
        if scope == "self":
            # The manifest's own row. It cannot carry its own digest, and `export/release.py` says
            # so in the row rather than omitting it — an omitted row would look like an oversight.
            continue
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


def verify_carried_hashes(repository_root: Path) -> int:
    """Re-hash every carried file whose sha256 is pinned in this module.

    The source layer and the four dictionaries used to be gated by their rows in
    `release_file_manifest.tsv`. That manifest is now regenerated by every metadata build, so it
    can no longer gate anything it does not itself produce; these hashes moved into code and this
    is what checks them. Returns the number recomputed so a caller can assert it is not zero.
    """
    checked = 0
    final_root = repository_root / "final"
    for relative, declared in sorted({**SOURCE_LAYER_HASHES, **DICTIONARY_HASHES}.items()):
        target = final_root / relative
        if not target.is_file():
            raise ContractError(f"carried release file is missing: final/{relative}")
        actual = sha256_file(target)
        if actual != declared:
            raise ContractError(
                f"final/{relative} sha256 {actual} does not match the hash pinned in "
                f"oracle/release.py ({declared})"
            )
        checked += 1
    return checked


def verify_build_manifest(repository_root: Path, spec: dict[str, Any]) -> None:
    """Check that what `final/` says it was built from is what the parity spec declares.

    The three fields checked before 2026-08-01 — `git_sha`, `schema_version`,
    `source_genbank_sha256`, plus `git_tree_clean` — described the 2.4.1 release writer's manifest.
    `export/release.py` writes a different and better one: no commit (see `code_digest`), and the
    raw archive identified by both of its hashes. The claim kept is the one that still means
    something: the release in `final/` was built from the raw archive the contract declares.
    """
    manifest = load_json(repository_root / BUILD_MANIFEST_PATH)
    inputs = manifest.get("inputs")
    if not isinstance(inputs, dict):
        raise ContractError(f"{BUILD_MANIFEST_PATH} declares no `inputs` block")
    checks = (
        ("raw_archive_sha256", spec["raw_input"]["archive_sha256"], "raw archive"),
        ("raw_uncompressed_sha256", spec["raw_input"]["uncompressed_sha256"], "raw uncompressed"),
        ("raw_record_count", spec["raw_input"]["record_count"], "raw record count"),
    )
    for field, expected, label in checks:
        actual = inputs.get(field)
        if actual != expected:
            raise ContractError(
                f"{BUILD_MANIFEST_PATH} inputs.{field}={actual!r} does not match parity {label} "
                f"{expected!r}"
            )
    if manifest.get("schema_version") != spec["source_schema_version"]:
        raise ContractError(
            f"{BUILD_MANIFEST_PATH} schema_version={manifest.get('schema_version')!r} does not "
            f"match parity source_schema_version {spec['source_schema_version']!r}"
        )


def verify_release_baseline(repository_root: Path, spec: dict[str, Any]) -> None:
    """Check that `final/` is the release this repository's inputs and code produce.

    Two of the six checks retired on 2026-08-01, with the metadata parity gate:
    `verify_expected_artifacts` and `verify_expected_counts` compared `final/` against 2.4.1's
    declared hashes and row counts, and `final/` no longer holds 2.4.1 — it holds this pipeline's
    own output, which carves 24,308 rows against the shipped 24,301 and derives twelve columns the
    release projected. Retaining them would have meant either failing every run or rewriting the
    numbers to match the build, and a contract rewritten from the thing it gates is not a contract.

    What is left is the part that was never self-certifying: the raw archive is authenticated, the
    build manifest is checked against it, the manifest's own hashes are recomputed, the carried
    files are re-hashed against pins in code, and every file under `final/` must be covered by one
    of the two.
    """
    verify_build_manifest(repository_root, spec)
    verify_raw_input(repository_root, spec["raw_input"])
    verify_release_manifest_hashes(repository_root)
    verify_carried_hashes(repository_root)
    verify_manifest_completeness(repository_root)


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
