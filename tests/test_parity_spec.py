"""The parity contract must describe the release that actually ships here.

Every test below mutates a copy of the real specification and asserts that verification
notices. A contract nothing can contradict is not a contract.

Five tests were removed on 2026-07-30 that restated, as plain assertions over the real spec, checks
`validate_parity_spec` and `verify_release_baseline` already make on the same file in the same run —
the frozen counts, the two policy booleans, `verify_release_baseline` itself, the
build-manifest/raw-hash tie, and the spec's existence. `validate_contracts` reaches all of them via
`tests/test_contracts.py::test_repository_contracts_validate`, and every mutation that reddened one
of the five reddened that test too. Restating an enforced check does not add a second guarantee; it
adds a second thing to update. Falsification of that enforcement is what belongs here.
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
    ContractError,
    validate_parity_spec,
    verify_raw_input,
)
from enterovirus_genbank_curated.oracle.release import (
    RELEASE_FILE_MANIFEST_PATH,
    read_tsv_gz,
    verify_build_manifest,
    verify_expected_artifacts,
    verify_expected_counts,
)


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


# The live instance of that bug is `final/source/normalized_tsv/comments.tsv.gz` — 18,476 real rows
# across 27,038 physical lines. A `test_shipped_comments_table_row_count_matches_its_dictionary`
# asserted the 18,476 against the shipped file; removed 2026-07-30. Those bytes are hash-gated by
# `evgc parity-source`, which compares all 24 source artifacts against
# `final/audit/release_file_manifest.tsv` and reports an altered release apart from a bad build.
#
# The mutation is worth recording because it came out lopsided rather than merely equivalent.
# Appending one byte to the shipped file left `read_tsv_gz` reporting 18,476 rows — gzip tolerates
# the trailing byte, so the removed assertion stayed green on a tampered release — while the corpus
# tier failed with `comments.tsv.gz: shipped artifact does not match its own manifest`. The count
# was the weaker of the two checks, not a second copy of the stronger one. And a change that *would*
# move the count necessarily moves the bytes, so parity sees that too.
#
# The behaviour that made the bug possible is covered above, against a fixture rather than against a
# number nothing in this repository can move.


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
