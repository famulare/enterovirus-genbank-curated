"""Hashes for the twenty files under `final/` that the release manifest does not declare.

`final/audit/release_file_manifest.tsv` covers 38 of the 58 files in `final/`. The other twenty —
the nineteen carved-in alignments plus the manifest itself — had no hash anywhere, so truncating
all nineteen to zero bytes, deleting one outright, and replacing shipped tables with the word
`garbage` left every gate reporting PASS (defect B7).

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
    "final/audit/release_file_manifest.tsv":
        "4ea3962d441fed1b984f95bf63f8f5632c81260ecd50a1dfb2b699c5c2e37b01",
}

SITE_MANIFEST = "site/data/manifest.json"

# Counts that make the completeness claim checkable rather than assertable. Each is re-derived in
# test_the_carried_set_is_exactly_final_minus_the_manifest.
EXPECTED_FINAL_FILES = 58
EXPECTED_MANIFEST_ROWS = 38
EXPECTED_FILE_BYTES_ROWS = 37


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


def test_this_file_is_the_sole_record_of_all_twenty(repository_root: Path) -> None:
    """One witness per hash, deliberately, and the limit of that stated rather than implied.

    A local site build regenerates `site/data/manifest.json`, which used to carry an independent
    declaration for seven of these. If it is present here, do not read that as a standing witness —
    it is a build artifact, not a committed cross-check, and the position is unchanged: this file is
    authoritative for all twenty.
    """
    assert len(CARRIED_SHA256) == 20
    assert set(CARRIED_SHA256) == set(CARRIED_FINAL_FILES)


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
