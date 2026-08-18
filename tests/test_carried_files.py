"""Hashes for the files under `final/` that the release manifest does not declare.

`final/audit/release_file_manifest.tsv` covers the 13 files `evgc build-metadata` writes — since
2026-08-01 `final/` is that build's destination, so the manifest describes the build and nothing
else. The other 50 are carried from 2.4.1: the nineteen carved-in alignments, the source layer, the
four dictionaries, and the two audit views the alignment layer still reads. Before this table
existed the alignments had no hash anywhere, so truncating all nineteen to zero bytes, deleting one
outright, and replacing shipped tables with the word `garbage` left every gate reporting PASS
(defect B7).

The source layer and the dictionaries are pinned a second time, in `oracle/release.py`, and that
duplication is deliberate rather than an oversight: `parity-source` needs those hashes at runtime,
not only under pytest. `test_the_pinned_set_is_exactly_the_declared_carried_set` requires the two
declarations to agree.

The hashes live here, in code, rather than in a new key inside `releases/2.4.1/parity.json`. A data
key would give these files a *single* declaration computed from the very bytes it gates and movable
by a data edit, which is defect B4 restated — strictly worse than the gap it closes. This is the
same pattern `tests/test_legacy_registry.py` already uses for `registry/legacy/`, and for the same
reason: the producer is gone, so the bytes are the artifact and moving one should take a reviewed
source edit.

**One witness per hash, and this file is it for all twenty.** A second, independent declaration in
`site/data/manifest.json` was tried and dropped: that tree is now built on deploy rather than
committed, and two declarations of the same hash cost maintenance without buying a guarantee, since
agreement makes one redundant and disagreement says nothing about which is right. The limit is
stated rather than papered over — this table detects corruption, and cannot detect a hash that was
wrong when written. The compensating control is that these are release bytes nothing in this
repository produces, so the only legitimate reason for one to change is a new release, at which
point it gains a real manifest row and leaves this table.
"""

from __future__ import annotations

import csv
import hashlib
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.oracle.release import (
    CARRIED_FINAL_FILES,
    IGNORED_FINAL_NAMES,
    RELEASE_FILE_MANIFEST_PATH,
    SOURCE_LAYER_HASHES,
    verify_manifest_completeness,
    verify_release_manifest_hashes,
)

# sha256 of each carried file. The source layer and `sequence_evidence.tsv.gz` are the shipped
# 2.4.1 bytes; the twenty-four alignment artifacts are this repository's own `alignment-build`
# output, so their pins move whenever a rebuild is promoted -- see `oracle/release.py`.
CARRIED_SHA256 = {
    "final/alignments/EV_unified.coverage.tsv.gz":
        "453cd965ed28651f60a3eed7ecf2b70cd49342972e931b6c291d47a8309a34d8",
    "final/alignments/EV_unified.provenance.json":
        "17655eafae2ea9d34281f81562ccf39bda3657c9fe6707c74a1a366cbe32e55e",
    "final/alignments/EV_unified.sto.gz":
        "d3f8272a9fd67c486e47bb257ec35c7146ed32349f96ad0e3aa8fa203740f1f8",
    "final/alignments/EV_unified_aln.fasta.gz":
        "dc76eea2a25931b8f8fff74b46b1c107c926a217791d5f20d7092f9a0fb5aebd",
    "final/alignments/NPEV_unified.coverage.tsv.gz":
        "3c34e327dcc6467c8384f33cea1c95cf44a8f704e04565af98ea0a16479e58f4",
    "final/alignments/NPEV_unified.provenance.json":
        "f9a0047626326ea13fd0326ef4d8740a62f11471f04f0db473d36127eb79cb27",
    "final/alignments/NPEV_unified.sto.gz":
        "99335620c5050afe3a2c0b925e4c34c02e578c917ce72a3be058842b3937b1ac",
    "final/alignments/NPEV_unified_aln.fasta.gz":
        "01fd138b7ba7eb6b012642db7aa7f300f5e3b6bb1602d3f29341b4eb34905abe",
    "final/alignments/POLIO_unified.coverage.tsv.gz":
        "ef81428ca221b89980a321912bd35ab3f79361852829ee4e3e35846cdcf60094",
    "final/alignments/POLIO_unified.provenance.json":
        "0340b4456dba6364c5b06d39927bb17445dd2248edd16d144fda8000fed03bbf",
    "final/alignments/POLIO_unified.sto.gz":
        "ce81c8bd5dd368fa141c02dd9c71acaabf73786598dd8cd609f67a4a85978a4e",
    "final/alignments/POLIO_unified_aln.fasta.gz":
        "ec7c8515fed16ce133a0764c1ec30f73ad3759e5bd6a9a879dcd03bee4698721",
    "final/alignments/PV1_unified.coverage.tsv.gz":
        "3cf89ab8c87dbb2fa0825211d255fd007253c7355387ce827a37dd4b846acf2d",
    "final/alignments/PV1_unified.provenance.json":
        "520d2c5aec767967cdc66a4b65e466561f998d8f3cad52fe6d0ba7a285c1ff65",
    "final/alignments/PV1_unified.sto.gz":
        "99c436dceaa87ca01eba17ea1dc1935852de1a285df0766f213642a8aa16fc69",
    "final/alignments/PV1_unified_aln.fasta.gz":
        "539bfe0866d07dac5d9cf809ce4f46276a563aefaeb4be01e1b8e39649ba50ef",
    "final/alignments/PV2_unified.coverage.tsv.gz":
        "7db9b71511c1adfecabde1723fd80ebb32554b0d2cc0ec604de2114c362df05e",
    "final/alignments/PV2_unified.provenance.json":
        "13d9c27b6b01ac10db634663ccc501b3ad093e25663a79453e003056e5cfb3bf",
    "final/alignments/PV2_unified.sto.gz":
        "e8ad0b31f6836c56bf838bd5e05c15b8f6465e274022bb2302e07f0661d5c542",
    "final/alignments/PV2_unified_aln.fasta.gz":
        "d447ed57226d9a462100afab33c7bee4aa6d8eb180e4c744ca7a75439db02034",
    "final/alignments/PV3_unified.coverage.tsv.gz":
        "486443786d3104e82e68b04e82df76dd870882999e848ab414bb311af23789e9",
    "final/alignments/PV3_unified.provenance.json":
        "1e5cefbe39cddf4b603009e83f4cf525017ae56e0451b3a8ea8261cc1968ccdf",
    "final/alignments/PV3_unified.sto.gz":
        "0f62202927e3d5b1ac5456ece4a045d90ff571db4c11cd88c04bb4835bd4b811",
    "final/alignments/PV3_unified_aln.fasta.gz":
        "d64f4da49ab7d8481a939d9824dbbdfd2ff0a11f16cbaf5cde344c0074cbdc30",
    "final/audit/sequence_evidence.tsv.gz":
        "5c5e55a9d38ab9fbb64b5cc204846af941257f7b803c8644f646375c9789c349",
    "final/source/genbank_source.duckdb":
        "fd7dbbc7f1c4ee5674aead335196c3019b122da80386d843fb9afb3e16969bb5",
    "final/source/normalized_tsv/comments.tsv.gz":
        "92b1b5a1331e71a254f94fbd1417f1e1a763b34446d84811407b63dcf7af8c95",
    "final/source/normalized_tsv/feature_location_parts.tsv.gz":
        "e5394a96dd20dfa3e174d2aae1bc5e060c2a6e43c23dd86763c1298c7711ee7b",
    "final/source/normalized_tsv/feature_qualifiers.tsv.gz":
        "55bffaefa54d417393750f0adbb187ae6e73aefc89ca81b7946f0fdbd9354a03",
    "final/source/normalized_tsv/features.tsv.gz":
        "e9960328759935ba1b3e0ad5aad968190be944b9d1d2337bf5a2ee113d1fa707",
    "final/source/normalized_tsv/record_accessions.tsv.gz":
        "3a59b4b566027b48ae443b328dad64283c50b9d3b13ec53d2b1ef08fc4ab182d",
    "final/source/normalized_tsv/record_keywords.tsv.gz":
        "57fb5efd58418adcb56e26a4678d9e1851e2bcb25b08e036885f4544250b9831",
    "final/source/normalized_tsv/record_taxonomy.tsv.gz":
        "2da64e6af64b6aec0582b7ac7118df795f4e71f78b73f08a6ac17686de19f9b9",
    "final/source/normalized_tsv/record_xrefs.tsv.gz":
        "56d88f48f32f03e292caf9b2de089abc179e60e777edfb1f7d218f928aac955c",
    "final/source/normalized_tsv/records.tsv.gz":
        "e9f0dac657c3c9daab4d7205c8e82022630e4db9e6a35824fc7df974bfd43b92",
    "final/source/normalized_tsv/reference_authors.tsv.gz":
        "913f8f4feb0352dfbb6356ae1c2c38db49c6d334927cd86378c955e0df69b092",
    "final/source/normalized_tsv/references.tsv.gz":
        "5cee850ba48e872a19ea76207fb6f58820a5393f6dea83bfa9c59b16cc474f9c",
    "final/source/normalized_tsv/structured_comment_fields.tsv.gz":
        "8ee441bf2c5561e7420e826a63dc09487afe6649df94c41f1655982e760bc490",
    "final/source/parquet/comments.parquet":
        "d15a6c707ae6756cd7253ba450e90eaa0f39c127997bc51da0bcfdb5ac251045",
    "final/source/parquet/feature_location_parts.parquet":
        "528b7a81a590f9305feafa9979f056083260d56a18bbd8a18cfff8343b38c58c",
    "final/source/parquet/feature_qualifiers.parquet":
        "86ae6efb1e9856fb569edc5aada955de212bf23d0cd78c87143e6a4dc0e933a0",
    "final/source/parquet/features.parquet":
        "b2f469f6e505f9bc77856e8a55796171e5d09beb78173ca73f1fa0f6c000e228",
    "final/source/parquet/record_accessions.parquet":
        "4a7dd0d82f0b67b719eca368dad1d547244d7fea89559bef7223fc5ce0ccfd22",
    "final/source/parquet/record_keywords.parquet":
        "bed7f82953244dfd722ca08b5fb693d616643e9319b3976b3d51fa58706fc29e",
    "final/source/parquet/record_taxonomy.parquet":
        "d14235a6b8ab6aec9d0c907b80407cac49041f364328f47eb6fa55d36bfd9720",
    "final/source/parquet/record_xrefs.parquet":
        "8633ca8483966d7378cea9841580edf2575df54552880963c3bb9a5c4a2434d7",
    "final/source/parquet/records.parquet":
        "ff4fc93dfd62522064aee29415c7b6d6bd6a35d22f7981dca376b36ad1d07704",
    "final/source/parquet/reference_authors.parquet":
        "f455df9d385da3b1600320d93b3999c2442e93da07993ea42a6e2e194f7db29a",
    "final/source/parquet/references.parquet":
        "0ea91a27cdc397fbdf084fb8d3d1633fd5c83e324452f321776532c86c13a146",
    "final/source/parquet/structured_comment_fields.parquet":
        "e2607a616cf9e5231d1946214d558f4e38b265ebdb35f2664be79aabd32b0c32",
}

# Counts that make the completeness claim checkable rather than assertable. Each is re-derived in
# test_the_carried_set_is_exactly_final_minus_the_manifest.
#
# The manifest grew by four on 2026-08-14 and the carried set shrank by the same four: the
# `final/dictionaries/` files now have a producer, so they moved from "bytes inherited from 2.4.1"
# to "written by this build". `EXPECTED_FINAL_FILES` does not move, because no file appeared or
# disappeared — only which side of the line it sits on.
EXPECTED_FINAL_FILES = 69
EXPECTED_MANIFEST_ROWS = 13 + 4 + 1 + 1
EXPECTED_FILE_BYTES_ROWS = 12 + 4 + 1 + 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_paths(repository_root: Path) -> set[str]:
    with (repository_root / RELEASE_FILE_MANIFEST_PATH).open(newline="", encoding="utf-8") as fh:
        return {f"final/{row['path']}" for row in csv.DictReader(fh, delimiter="\t")}


@pytest.fixture
def synthetic_release(tmp_path: Path) -> Path:
    """A miniature `final/` with its own manifest, for mutation tests.

    Mutating a copy of the real tree would mean duplicating ~100 MB per test. The checks under test
    read only the manifest and walk `final/`, so a three-file release exercises them exactly.
    """
    root = tmp_path / "repo"
    (root / "final/canonical").mkdir(parents=True)
    (root / "final/audit").mkdir(parents=True)
    (root / "final/alignments").mkdir(parents=True)

    declared = root / "final/canonical/table.tsv.gz"
    declared.write_bytes(b"declared payload")
    carried = root / "final/alignments/CARRIED_unified.sto.gz"
    carried.write_bytes(b"carried payload")

    manifest = root / RELEASE_FILE_MANIFEST_PATH
    manifest.write_text(
        "path\thash_scope\tsha256\tauthoritative\tnotes\n"
        f"canonical/table.tsv.gz\tfile_bytes\t{sha256(declared)}\tTRUE\t\n"
        "source/genbank_source.duckdb\tlogical_content\t" + "0" * 64 + "\tFALSE\tno computer\n",
        encoding="utf-8",
    )
    # The logical_content row is declared but has no file; verify_release_manifest_hashes checks
    # existence for every scope, so give it one.
    (root / "final/source").mkdir(parents=True)
    (root / "final/source/genbank_source.duckdb").write_bytes(b"db")
    return root


def patched_carried(monkeypatch, *paths: str) -> None:
    monkeypatch.setattr(
        "enterovirus_genbank_curated.oracle.release.CARRIED_FINAL_FILES", frozenset(paths)
    )


# --- the pinned hashes -------------------------------------------------------------------------


@pytest.mark.parametrize("relative", sorted(CARRIED_SHA256))
def test_each_carried_file_matches_its_pinned_hash(repository_root: Path, relative: str) -> None:
    path = repository_root / relative
    assert path.is_file(), f"{relative} is missing; it cannot be regenerated from this repository"
    assert sha256(path) == CARRIED_SHA256[relative], (
        f"{relative} has changed. These files were produced by a private pipeline that is not in "
        f"this repository, so there is nothing to re-derive them from; if the change is "
        f"deliberate, update CARRIED_SHA256 and say why."
    )


def test_the_pinned_set_is_exactly_the_declared_carried_set() -> None:
    """CARRIED_FINAL_FILES governs completeness; CARRIED_SHA256 governs bytes. Neither may drift."""
    assert set(CARRIED_SHA256) == set(CARRIED_FINAL_FILES)


def test_this_file_is_the_sole_record_of_every_carried_file() -> None:
    """One witness per hash, deliberately, and the limit of that stated rather than implied.

    A local site build regenerates `site/data/manifest.json`, which used to carry an independent
    declaration for seven of these. If it is present here, do not read that as a standing witness —
    it is a build artifact, not a committed cross-check, and the position is unchanged: this file is
    authoritative for every carried file.

    The exception is the source layer, which `oracle/release.py` also pins because `parity-source`
    reads it outside pytest; the assertion below requires the two to agree rather than treating
    either as the copy. The four dictionaries were a second exception until 2026-08-14, when
    `export/dictionaries.py` gave them a producer — they are build artifacts now and the release
    manifest covers them.
    """
    assert len(CARRIED_SHA256) == EXPECTED_FINAL_FILES - EXPECTED_MANIFEST_ROWS
    assert set(CARRIED_SHA256) == set(CARRIED_FINAL_FILES)
    for relative, declared in SOURCE_LAYER_HASHES.items():
        assert CARRIED_SHA256[f"final/{relative}"] == declared


# --- the completeness derivation --------------------------------------------------------------


def test_the_carried_set_is_exactly_final_minus_the_manifest(repository_root: Path) -> None:
    """Derive the twenty rather than trusting the constant, so the number lives next to a proof."""
    present = {
        str(p.relative_to(repository_root))
        for p in (repository_root / "final").rglob("*")
        if p.is_file() and p.name not in IGNORED_FINAL_NAMES
    }
    declared = manifest_paths(repository_root)
    assert len(present) == EXPECTED_FINAL_FILES
    assert len(declared) == EXPECTED_MANIFEST_ROWS
    assert present - declared == set(CARRIED_FINAL_FILES)
    assert len(CARRIED_FINAL_FILES) == EXPECTED_FINAL_FILES - EXPECTED_MANIFEST_ROWS


def test_the_manifest_hash_check_covers_every_file_bytes_row(repository_root: Path) -> None:
    """Before this change six of thirty-seven were recomputed; assert the count, not the intent."""
    assert verify_release_manifest_hashes(repository_root) == EXPECTED_FILE_BYTES_ROWS


def test_the_shipped_release_passes_both_checks(repository_root: Path) -> None:
    verify_release_manifest_hashes(repository_root)
    verify_manifest_completeness(repository_root)


# --- mutations: each check, proven to fire ----------------------------------------------------


def test_a_corrupted_declared_file_fails_the_hash_check(synthetic_release: Path) -> None:
    (synthetic_release / "final/canonical/table.tsv.gz").write_bytes(b"garbage")
    with pytest.raises(ContractError, match="does not match the hash"):
        verify_release_manifest_hashes(synthetic_release)


def test_a_missing_declared_file_fails_the_hash_check(synthetic_release: Path) -> None:
    (synthetic_release / "final/canonical/table.tsv.gz").unlink()
    with pytest.raises(ContractError, match="which does not exist"):
        verify_release_manifest_hashes(synthetic_release)


def test_a_missing_logical_content_file_still_fails(synthetic_release: Path) -> None:
    """`logical_content` skips hashing, but existence is still checked; otherwise deleting the
    DuckDB convenience database would pass silently."""
    (synthetic_release / "final/source/genbank_source.duckdb").unlink()
    with pytest.raises(ContractError, match="which does not exist"):
        verify_release_manifest_hashes(synthetic_release)


def test_an_undeclared_new_file_fails_completeness(synthetic_release: Path, monkeypatch) -> None:
    patched_carried(
        monkeypatch, "final/alignments/CARRIED_unified.sto.gz", RELEASE_FILE_MANIFEST_PATH
    )
    (synthetic_release / "final/alignments/SNEAKED_IN.sto.gz").write_bytes(b"x")
    with pytest.raises(ContractError, match="covered by neither"):
        verify_manifest_completeness(synthetic_release)


def test_a_deleted_carried_file_fails_completeness(synthetic_release: Path, monkeypatch) -> None:
    """The direction B7's mutation exercised: deleting a carried file outright."""
    patched_carried(
        monkeypatch, "final/alignments/CARRIED_unified.sto.gz", RELEASE_FILE_MANIFEST_PATH
    )
    (synthetic_release / "final/alignments/CARRIED_unified.sto.gz").unlink()
    with pytest.raises(ContractError, match="do not exist"):
        verify_manifest_completeness(synthetic_release)


def test_os_metadata_debris_does_not_demand_a_hash(
    synthetic_release: Path, monkeypatch
) -> None:
    """`.DS_Store` is never release content, and the walk reads the filesystem, not the index.

    macOS writes one into any directory someone opens in Finder. It is gitignored and has never
    shipped, but the completeness check has to walk the filesystem — finding undeclared files is the
    entire point — so it would otherwise demand a hash for Finder droppings.
    """
    patched_carried(
        monkeypatch, "final/alignments/CARRIED_unified.sto.gz", RELEASE_FILE_MANIFEST_PATH
    )
    verify_manifest_completeness(synthetic_release)  # clean baseline, so the debris is the variable
    (synthetic_release / "final/.DS_Store").write_bytes(b"\x00\x01")
    (synthetic_release / "final/canonical/.DS_Store").write_bytes(b"\x00\x01")
    verify_manifest_completeness(synthetic_release)


def test_debris_is_skipped_by_name_not_by_being_a_dotfile(
    synthetic_release: Path, monkeypatch
) -> None:
    """An undeclared dotfile that is not on the ignore list must still fail.

    Skipping every name starting with a dot would be the easy fix and would also hide a real
    artifact named that way, which is the failure mode this check exists to catch.
    """
    patched_carried(
        monkeypatch, "final/alignments/CARRIED_unified.sto.gz", RELEASE_FILE_MANIFEST_PATH
    )
    (synthetic_release / "final/.hidden_artifact").write_bytes(b"payload")
    with pytest.raises(ContractError, match="covered by neither"):
        verify_manifest_completeness(synthetic_release)


def test_a_file_both_carried_and_declared_fails_completeness(
    synthetic_release: Path, monkeypatch
) -> None:
    """Refuses the ambiguity outright rather than letting one declaration silently win."""
    patched_carried(
        monkeypatch,
        "final/alignments/CARRIED_unified.sto.gz",
        "final/canonical/table.tsv.gz",
    )
    with pytest.raises(ContractError, match="cannot be both carried and declared"):
        verify_manifest_completeness(synthetic_release)


def test_a_manifest_with_no_file_bytes_rows_is_refused(synthetic_release: Path) -> None:
    """A check that verifies nothing must fail rather than report success."""
    (synthetic_release / RELEASE_FILE_MANIFEST_PATH).write_text(
        "path\thash_scope\tsha256\tauthoritative\tnotes\n"
        "source/genbank_source.duckdb\tlogical_content\t" + "0" * 64 + "\tFALSE\t\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="declared no file_bytes hashes"):
        verify_release_manifest_hashes(synthetic_release)


def test_an_unknown_hash_scope_is_refused(synthetic_release: Path) -> None:
    (synthetic_release / RELEASE_FILE_MANIFEST_PATH).write_text(
        "path\thash_scope\tsha256\tauthoritative\tnotes\n"
        "canonical/table.tsv.gz\tvibes\t" + "0" * 64 + "\tTRUE\t\n",
        encoding="utf-8",
    )
    with pytest.raises(ContractError, match="unknown hash_scope"):
        verify_release_manifest_hashes(synthetic_release)
