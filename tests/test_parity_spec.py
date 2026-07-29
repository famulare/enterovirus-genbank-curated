"""The parity contract must describe the release that actually ships here.

Every test below mutates a copy of the real specification and asserts that verification
notices. A contract nothing can contradict is not a contract.
"""

import copy
import csv
import gzip
import json
import shutil
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import (
    EXPECTED_BASELINE_COUNTS,
    PARITY_SPEC_PATH,
    RELEASE_FILE_MANIFEST_PATH,
    ContractError,
    read_tsv_gz,
    validate_parity_spec,
    verify_build_manifest,
    verify_expected_artifacts,
    verify_expected_counts,
    verify_raw_input,
    verify_release_baseline,
)


def test_parity_spec_records_frozen_release_counts(parity_spec: dict) -> None:
    assert parity_spec["expected_counts"] == EXPECTED_BASELINE_COUNTS


def test_parity_spec_never_treats_final_as_input(parity_spec: dict) -> None:
    assert parity_spec["policy"]["existing_final_is_pipeline_input"] is False
    assert parity_spec["policy"]["baseline_release_mutable"] is False


def test_shipped_release_matches_the_parity_contract(
    repository_root: Path, parity_spec: dict
) -> None:
    verify_release_baseline(repository_root, parity_spec)


def test_undeclared_parity_keys_are_rejected(tmp_path: Path, parity_spec: dict) -> None:
    spec = copy.deepcopy(parity_spec)
    spec["allow_everything"] = True
    path = tmp_path / "parity.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    with pytest.raises(ContractError, match="undeclared keys"):
        validate_parity_spec(path)


def test_falsified_artifact_hash_is_caught(repository_root: Path, parity_spec: dict) -> None:
    artifacts = copy.deepcopy(parity_spec["expected_artifacts"])
    artifacts[0]["sha256"] = "0" * 64
    with pytest.raises(ContractError, match="disagrees with the release manifest"):
        verify_expected_artifacts(repository_root, artifacts)


def test_artifact_absent_from_the_release_manifest_is_caught(
    repository_root: Path, parity_spec: dict
) -> None:
    artifacts = copy.deepcopy(parity_spec["expected_artifacts"])
    artifacts[0]["path"] = "final/audit/not_a_real_table.tsv.gz"
    with pytest.raises(ContractError, match="not declared in"):
        verify_expected_artifacts(repository_root, artifacts)


def test_falsified_raw_archive_hash_is_caught(
    repository_root: Path, parity_spec: dict
) -> None:
    raw = copy.deepcopy(parity_spec["raw_input"])
    raw["archive_sha256"] = "0" * 64
    with pytest.raises(ContractError, match="does not match the parity contract"):
        verify_raw_input(repository_root, raw)


def test_falsified_archive_member_size_is_caught(
    repository_root: Path, parity_spec: dict
) -> None:
    raw = copy.deepcopy(parity_spec["raw_input"])
    raw["uncompressed_bytes"] = raw["uncompressed_bytes"] - 1
    with pytest.raises(ContractError, match="contract declares"):
        verify_raw_input(repository_root, raw)


def test_missing_archive_member_is_caught(repository_root: Path, parity_spec: dict) -> None:
    raw = copy.deepcopy(parity_spec["raw_input"])
    raw["archive_member"] = "not_in_the_archive.gb"
    with pytest.raises(ContractError, match="does not contain the declared member"):
        verify_raw_input(repository_root, raw)


@pytest.mark.parametrize("key", sorted(EXPECTED_BASELINE_COUNTS))
def test_falsified_counts_are_caught(repository_root: Path, key: str) -> None:
    counts = dict(EXPECTED_BASELINE_COUNTS)
    counts[key] += 1
    with pytest.raises(ContractError, match=key):
        verify_expected_counts(repository_root, counts)


def test_build_manifest_disagreement_is_caught(
    repository_root: Path, parity_spec: dict
) -> None:
    spec = copy.deepcopy(parity_spec)
    spec["source_release_commit"] = "0" * 40
    with pytest.raises(ContractError, match="git_sha"):
        verify_build_manifest(repository_root, spec)


def test_raw_archive_is_tied_to_the_release_build_manifest(
    repository_root: Path, parity_spec: dict
) -> None:
    """The shipped raw archive must be the snapshot the release says it was built from."""
    manifest = json.loads(
        (repository_root / "final/audit/build_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["source_genbank_sha256"] == parity_spec["raw_input"]["uncompressed_sha256"]


def test_parity_spec_path_constant_points_at_the_shipped_contract(repository_root: Path) -> None:
    assert (repository_root / PARITY_SPEC_PATH).is_file()


def test_quoted_multiline_fields_are_counted_as_one_row(tmp_path: Path) -> None:
    """Release tables are written QUOTE_MINIMAL; reading them as plain TSV overcounts rows."""
    path = tmp_path / "t.tsv.gz"
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["id", "text"])
        writer.writerow(["a", "one\ntext\nspanning\nlines"])
        writer.writerow(["b", "plain"])
    header, rows = read_tsv_gz(path)
    assert header == ["id", "text"]
    assert len(rows) == 2
    assert rows[0][1] == "one\ntext\nspanning\nlines"


def test_shipped_comments_table_row_count_matches_its_dictionary(repository_root: Path) -> None:
    """The live instance of the bug above: 18,476 rows across 27,038 physical lines."""
    _, rows = read_tsv_gz(repository_root / "final/source/normalized_tsv/comments.tsv.gz")
    assert len(rows) == 18476


def test_drifted_artifact_bytes_are_caught(
    tmp_path: Path, repository_root: Path, parity_spec: dict
) -> None:
    """Both declared hashes can agree with each other and still not match the shipped file."""
    artifact = next(
        item for item in parity_spec["expected_artifacts"] if item["hash_scope"] == "file_bytes"
    )
    for relative in (RELEASE_FILE_MANIFEST_PATH, artifact["path"]):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository_root / relative, target)

    perturbed = tmp_path / artifact["path"]
    perturbed.write_bytes(perturbed.read_bytes() + b"\x00")
    with pytest.raises(ContractError, match="does not match the parity contract"):
        verify_expected_artifacts(tmp_path, [copy.deepcopy(artifact)])
