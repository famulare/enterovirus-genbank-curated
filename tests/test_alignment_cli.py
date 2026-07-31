"""Exercise the three alignment CLI branches by calling `cli.main` directly.

`ci.yml` records the convention this follows: a `cli.py` branch is covered by a fast test calling
`cli.main([...])`, not by a workflow step that redoes work pytest has already done.

All three verbs are deliberately cheap. `alignment-population` reads metadata and runs no aligner,
so it is the 1-to-1 claim in executable form. `alignment-toolchain` only inspects an installed
prefix, and skips when that prefix is absent. `alignment-verify-seeds` re-hashes the committed
covariance-model core and needs no native toolchain at all, so it never skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated import cli
from enterovirus_genbank_curated.align import contract

TOOLCHAIN_PRESENT = (
    Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft"
).exists()


def test_alignment_population_reports_every_artifact(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["alignment-population", "--repository-root", str(repository_root)]) == 0
    out = capsys.readouterr().out
    assert "canonical records: 24301" in out
    for name, spec in contract.ARTIFACTS.items():
        assert f"{name}  {spec.expected_rows} rows" in out, name
    # `UNEXPECTED` is what the command prints when a population misses its declared count, so its
    # absence is the actual assertion here rather than a formatting detail.
    assert "UNEXPECTED" not in out


def test_alignment_population_accepts_a_single_artifact(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main(
        [
            "alignment-population",
            "--repository-root",
            str(repository_root),
            "--artifact",
            "PV3_unified",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "PV3_unified  1693 rows" in out
    assert "POLIO_unified" not in out


def test_alignment_population_rejects_an_unknown_artifact(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Fail closed with a nonzero exit, not a silently empty report."""
    exit_code = cli.main(
        [
            "alignment-population",
            "--repository-root",
            str(repository_root),
            "--artifact",
            "PV9_unified",
        ]
    )
    assert exit_code == 1
    assert "unknown alignment" in capsys.readouterr().err


@pytest.mark.skipif(not TOOLCHAIN_PRESENT, reason="pixi align environment is not installed")
def test_alignment_toolchain_passes_against_the_declaration(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["alignment-toolchain", "--repository-root", str(repository_root)]) == 0
    out = capsys.readouterr().out
    assert "alignment toolchain: PASS" in out
    assert "mafft" in out and "cmalign" in out


def test_alignment_toolchain_fails_loudly_without_a_prefix(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing environment must name the command that reconstructs it."""
    assert cli.main(["alignment-toolchain", "--repository-root", str(tmp_path)]) == 1
    assert "pixi install --locked -e align" in capsys.readouterr().err


def test_alignment_verify_seeds_needs_no_toolchain(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The one alignment verb that must pass on every push with no native binary installed."""
    assert cli.main(["alignment-verify-seeds", "--repository-root", str(repository_root)]) == 0
    out = capsys.readouterr().out
    assert "alignment seeds: PASS (30 files" in out


def test_alignment_verify_seeds_fails_loudly_without_the_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["alignment-verify-seeds", "--repository-root", str(tmp_path)]) == 1
    assert "does not exist" in capsys.readouterr().err
