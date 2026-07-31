"""A committed release must be what the committed code produces.

The failure this exists to prevent, observed 2026-07-31: `derive/partition.py` changed so that a
curated classification entails poliovirus membership, which moved 781 cells and `vouched_rows` from
9,670 to 9,929. The code change, the moved parity pins and the tests were all committed — and
`release/3.1.0/` was not rebuilt. It went into git describing a build that no longer existed, with a
`code_sha256` naming code that was no longer in the tree.

Nothing caught it. Every other gate compares the *build* against `final/`, so a build-time defect
fails loudly and a stale *artifact* passes silently. The whole point of hashing four determinants
into the manifest is to make that detectable, and until this test nothing actually read them back.

Cheap on purpose: it re-hashes the four determinants and compares, without rebuilding. A drift here
does not mean the release is wrong, it means nobody has demonstrated it is right — so the remedy is
always the same, rebuild it and commit the result:

    evgc build-metadata --output release/<version> --guard-inputs
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import DECISIONS_LEDGER_PATH, sha256_file
from enterovirus_genbank_curated.export.release import (
    BUILD_MANIFEST_RELATIVE,
    RELEASE_VERSION,
    code_digest,
)
from enterovirus_genbank_curated.registry.rules import RULES_CATALOG_PATH


def released_manifest(repository_root: Path) -> dict:
    path = repository_root / "release" / RELEASE_VERSION / BUILD_MANIFEST_RELATIVE
    assert path.is_file(), (
        f"{path} does not exist, so RELEASE_VERSION {RELEASE_VERSION} names a release that was "
        f"never built. Bumping the constant is not shipping the release."
    )
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def test_the_committed_release_was_built_by_the_committed_code(repository_root: Path) -> None:
    """The determinant that actually drifts. Code changes daily; the archive never does."""
    manifest = released_manifest(repository_root)
    assert manifest["code_sha256"] == code_digest(repository_root), (
        f"release/{RELEASE_VERSION}/ was built by different code than is in the tree now. Rebuild "
        f"it before committing: evgc build-metadata --output release/{RELEASE_VERSION} "
        f"--guard-inputs"
    )


def test_the_committed_release_was_built_from_the_committed_registry(
    repository_root: Path,
) -> None:
    """Separated from the code check so a failure says *which* determinant moved.

    A ledger edit and a code edit need the same remedy but mean different things: one is new
    curation, the other is new logic, and a single combined assertion would not say which.
    """
    manifest = released_manifest(repository_root)
    assert manifest["inputs"]["decisions_sha256"] == sha256_file(
        repository_root / DECISIONS_LEDGER_PATH
    ), f"the decision ledger has changed since release/{RELEASE_VERSION}/ was built"
    assert manifest["inputs"]["rules_sha256"] == sha256_file(
        repository_root / RULES_CATALOG_PATH
    ), f"the rule catalog has changed since release/{RELEASE_VERSION}/ was built"


def test_the_release_states_its_own_version(repository_root: Path) -> None:
    """Guards the copy-a-directory mistake, which the hashes above cannot see."""
    manifest = released_manifest(repository_root)
    assert manifest["release_version"] == RELEASE_VERSION


@pytest.mark.slow
def test_every_file_the_release_declares_is_present_and_unaltered(repository_root: Path) -> None:
    """The manifest is only a claim until something recomputes it.

    Covers the reverse direction too: an artifact in the directory that the manifest does not
    declare means the release shipped a file nothing vouches for.
    """
    from enterovirus_genbank_curated.export.release import FILE_MANIFEST_RELATIVE
    from enterovirus_genbank_curated.oracle.release import load_release_file_manifest

    root = repository_root / "release" / RELEASE_VERSION
    declared = load_release_file_manifest(root / FILE_MANIFEST_RELATIVE)
    for relative, (scope, expected) in sorted(declared.items()):
        artifact = root / relative
        assert artifact.is_file(), f"{relative} is declared but absent"
        if scope != "file_bytes":
            continue
        assert sha256_file(artifact) == expected, f"{relative} does not match its declared hash"

    present = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert present == set(declared), (
        f"undeclared artifacts in release/{RELEASE_VERSION}/: {sorted(present - set(declared))}"
    )
