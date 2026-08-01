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
    DICTIONARY_HASHES,
    IGNORED_FINAL_NAMES,
    RELEASE_FILE_MANIFEST_PATH,
    SOURCE_LAYER_HASHES,
    verify_manifest_completeness,
    verify_release_manifest_hashes,
)

# sha256 of each carried file, measured from the shipped 2.4.1 release.
CARRIED_SHA256 = {
    "final/alignments/EV_unified.provenance.json":
        "680a0830cb2cd29cdcc353924d3cb67e45ed42303c78cd76b9411bb9797fb3ad",
    "final/alignments/EV_unified.sto.gz":
        "32600d33fada27ea6ea8f9675d59c9247659512d00e2612a9a248c27f19375cf",
    "final/alignments/EV_unified_aln.fasta.gz":
        "b3d02f1b5c9eaa778f28f377d34ed19af325e740aec053baa92ec3ba5aadf355",
    "final/alignments/NPEV_unified.provenance.json":
        "ff870a1c257818fd5492d329ff42744c0f26f903d0c6da8a016660b618ad99b7",
    "final/alignments/NPEV_unified.sto.gz":
        "eea7ae3e318d813800dd5b73b809ccbfd248fe6b4db2d3562a976933248234f6",
    "final/alignments/NPEV_unified_aln.fasta.gz":
        "ed75de17f879046ee1136ba6fcafe149bf02bb6840c9c7540e04725cef757309",
    "final/alignments/POLIO_unified.provenance.json":
        "06a8fc2c5ccc5ea7116d3c7c44629ae0219cc8f4789bacbd633f78ef165d5dd8",
    "final/alignments/POLIO_unified.sto.gz":
        "a22ab105556ed9a8eecdd33f8cae3b062e8b5643134f1429a4be4d6d8372a009",
    "final/alignments/POLIO_unified_aln.fasta.gz":
        "66ebea8d67c0404f6c3d0c1385330ecd67b55459b35a889568c95278d768ed7e",
    "final/alignments/PV1_unified.sto.gz":
        "b9db50b0c622c8d64acd214337b908caf2ea49395b042494c137b8820a72f36d",
    "final/alignments/PV1_unified_aln.fasta.gz":
        "c478040dc4dceb03ffee5df1b9a51d0f448557136dc7aad48b12b18091c1c03e",
    "final/alignments/PV2_unified.sto.gz":
        "0191b8e886e60396b8a2f9bc5bfacf45f8482dfcff95e5144c6b11e1f87cf98c",
    "final/alignments/PV2_unified_aln.fasta.gz":
        "422dd98a4c1eecdad4652b47152a03479e6cc99a582feda39406a4bb8a1a5221",
    "final/alignments/PV3_unified.sto.gz":
        "2d695a0334a8ca6ac4630639ed272004f480776f174289ea258feeb839caa2e7",
    "final/alignments/PV3_unified_aln.fasta.gz":
        "9f613ee111ba9b89f9ef15f2b53b152d0fbb837e27330ec2c28065ecfc2d23ed",
    "final/alignments/reference_alignment_provenance.json":
        "e063bdfa40d89837e0311079c8fe4b1c6c9bbb9277f1d15ef1c4ad97f54d9261",
    "final/alignments/reference_msa_provenance.json":
        "ccdaa427a9269be6b1d25436b7162404e2f7ad241e1ade9e2d301461fbec9c9b",
    "final/alignments/reference_region_coordinates.tsv":
        "41420f9e5a5d3804f6370c0b41fa487365e5dc0a85e1f85c191082f15f9551e1",
    "final/alignments/unified_stockholm_provenance.json":
        "6428df2a82825d729a35606402c36c8ed354ee2049d0b0da198d57ce7fcad872",
    "final/audit/record_disposition.tsv.gz":
        "2de98c63e822ec5352921a71bb801d99f3ed5639ce4f1020dbe22c88c835871a",
    "final/audit/sequence_evidence.tsv.gz":
        "5c5e55a9d38ab9fbb64b5cc204846af941257f7b803c8644f646375c9789c349",
    "final/dictionaries/audit_data_dictionary.tsv":
        "222ef799baa1ae7f292cc652237dd1fc9e474199eb8e8d2a76f120a33d0c2098",
    "final/dictionaries/canonical_data_dictionary.tsv":
        "8fc475c7ac7482e7602339fb0257ce95a4db9e9fee164570fb9903750651df70",
    "final/dictionaries/controlled_vocabularies.tsv":
        "7fb35d08de7796793456c634f343eaa7f55823302052a3940b4bdc9efaeb8d4a",
    "final/dictionaries/source_schema_dictionary.tsv":
        "e946d0ea4e77743338195052d8823dab7551e26214f5ecc5302a60b7a99fde1b",
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
EXPECTED_FINAL_FILES = 63
EXPECTED_MANIFEST_ROWS = 13
EXPECTED_FILE_BYTES_ROWS = 12


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


def test_this_file_is_the_sole_record_of_every_carried_file(repository_root: Path) -> None:
    """One witness per hash, deliberately, and the limit of that stated rather than implied.

    A local site build regenerates `site/data/manifest.json`, which used to carry an independent
    declaration for seven of these. If it is present here, do not read that as a standing witness —
    it is a build artifact, not a committed cross-check, and the position is unchanged: this file is
    authoritative for every carried file.

    The exception is the source layer and the dictionaries, which `oracle/release.py` also pins
    because `parity-source` reads them outside pytest; the assertion below requires the two to
    agree rather than treating either as the copy.
    """
    assert len(CARRIED_SHA256) == EXPECTED_FINAL_FILES - EXPECTED_MANIFEST_ROWS
    assert set(CARRIED_SHA256) == set(CARRIED_FINAL_FILES)
    for relative, declared in {**SOURCE_LAYER_HASHES, **DICTIONARY_HASHES}.items():
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
