"""Exercise the three alignment CLI branches by calling `cli.main` directly.

`ci.yml` records the convention this follows: a `cli.py` branch is covered by a fast test calling
`cli.main([...])`, not by a workflow step that redoes work pytest has already done.

All three verbs are deliberately cheap. `alignment-population` reads metadata and runs no aligner,
so it is the 1-to-1 claim in executable form. `alignment-toolchain` only inspects an installed
prefix, and skips when that prefix is absent. `alignment-verify-seeds` re-hashes the committed
covariance-model core and needs no native toolchain at all, so it never skips.
"""

from __future__ import annotations

import subprocess
import sys
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
    assert "canonical records: 24308" in out
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
    assert "PV3_unified  1597 rows" in out
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


# --- the verbs that read a built tree ------------------------------------------------------------

BUILT_DIR = Path(__file__).resolve().parents[1] / "derived/alignments"
BUILT_PV3 = BUILT_DIR / "PV3_unified.sto.gz"
REQUIRES_BUILD = pytest.mark.skipif(
    not BUILT_PV3.is_file(), reason="no built alignment in derived/alignments/"
)


@REQUIRES_BUILD
def test_alignment_verify_passes_on_a_built_artifact(
    repository_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main([
        "alignment-verify", "--repository-root", str(repository_root),
        "--output-dir", str(BUILT_DIR), "--artifact", "PV3_unified",
    ])
    out = capsys.readouterr()
    assert exit_code == 0, out.err
    assert "alignment verify: PASS" in out.out


@REQUIRES_BUILD
def test_alignment_shape_reports_the_declared_delta(
    repository_root: Path, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Runs against a copy so the verb's own report files do not land in the built tree."""
    import shutil

    for path in BUILT_DIR.glob("PV3_unified*"):
        shutil.copy(path, tmp_path / path.name)
    exit_code = cli.main([
        "alignment-shape", "--repository-root", str(repository_root),
        "--output-dir", str(tmp_path), "--artifact", "PV3_unified",
    ])
    out = capsys.readouterr()
    assert exit_code == 0, out.err
    assert "vs 2.4.1" in out.out
    assert (tmp_path / "shape_report.json").is_file()
    assert (tmp_path / "shape_report.md").is_file()


def test_alignment_verify_rejects_an_unknown_artifact(
    repository_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    exit_code = cli.main([
        "alignment-verify", "--repository-root", str(repository_root),
        "--output-dir", str(tmp_path), "--artifact", "PV9_unified",
    ])
    assert exit_code == 1
    assert "unknown alignment" in capsys.readouterr().err


# --- the cheap verbs must stay cheap -------------------------------------------------------------

NO_CHILD_SCRIPT = """
import sys
spawned = []
sys.addaudithook(
    lambda event, args: spawned.append(event)
    if event in ("subprocess.Popen", "os.exec", "os.posix_spawn", "os.fork")
    else None
)
from enterovirus_genbank_curated import cli
code = cli.main({argv!r})
assert code == 0, f"verb failed with {{code}}"
assert not spawned, f"spawned a child process: {{spawned}}"
print("NO CHILD")
"""


@pytest.mark.parametrize("verb", ["alignment-population", "alignment-verify-seeds"])
def test_the_cheap_verbs_spawn_no_child_process(repository_root: Path, verb: str) -> None:
    """The property that keeps the push-time gate cheap. If one of these ever needs to *run* mafft
    it has inherited the multi-hour job's cost, and this is what says so out loud. Asserted with an
    audit hook rather than the input guard, because `align/` legitimately reads `final/` and the
    input guard would refuse that for an unrelated reason.
    """
    argv = [verb, "--repository-root", str(repository_root)]
    result = subprocess.run(
        [sys.executable, "-c", NO_CHILD_SCRIPT.format(argv=argv)],
        capture_output=True, text=True, cwd=repository_root, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "NO CHILD" in result.stdout
