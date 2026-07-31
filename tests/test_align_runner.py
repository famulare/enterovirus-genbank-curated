"""`align.runner.run_tool`: the one place this codebase calls `subprocess`, exercised end to end.

Every test runs in its own interpreter, via `subprocess`, for the same reason
`tests/test_tool_sandbox.py` does: an audit hook cannot be uninstalled, and `install_tool_guard`
called a second time in one process leaves the *first* guard's hook still installed and still
unarmed — verified directly: a second `install_tool_guard` call in the same process refused
`align.toolchain.resolve()`'s own internal version-probe subprocess call, which never goes through
`run_tool` and was never meant to be armed at all. One guard, one process, matching how the real
build uses it (`evgc build-alignments` installs exactly one tool guard for the life of the CLI
invocation).

Fail-closed checks (unknown tool, no declared output, bad basenames) use a *fake* toolchain built
without touching `.pixi/`, so they run — and are exercised by the cheap CI job — with no native
aligner installed at all. The real-exec tests use the genuine resolved toolchain and are skipped
without it, but they are not optional polish: they are what proves the whole stack (guard, runner,
toolchain) works together, not just in isolation.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)

# A structurally valid, never-really-executed Toolchain, built without touching `.pixi/envs/` —
# the fake binaries are real, tiny shell scripts, created under `.pixi/` (already gitignored, and
# inside the clone, which `install_tool_guard` requires of every allowlisted executable) rather
# than under a tmp_path outside it.
FAKE_PREAMBLE = """
import tempfile
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import runner, scratch as sc, toolchain as tc
from enterovirus_genbank_curated.contracts import ContractError

ROOT = Path({root!r})
scratch = sc.create()
fake_bin_dir = Path(tempfile.mkdtemp(dir=ROOT / ".pixi"))
tools = {{}}
for name in ("mafft", "mafft-linsi", "cmalign"):
    path = fake_bin_dir / name
    path.write_text("#!/bin/sh\\nexit 0\\n")
    path.chmod(0o755)
    tools[name] = tc.Tool(
        name=name, package="fake", path=path, version="0.0", build="fake_0",
        self_reported="fake 0.0", sha256="0" * 64,
    )
toolchain = tc.Toolchain(
    environment="fake", platform="fake", prefix=fake_bin_dir, bin_dir=fake_bin_dir, tools=tools,
)
guard = se.install_tool_guard(
    ROOT, scratch_root=scratch.root,
    allowed_executables=frozenset(str(t.path) for t in tools.values()),
)
"""

REAL_PREAMBLE = """
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import runner, scratch as sc, toolchain as tc
from enterovirus_genbank_curated.contracts import ContractError

ROOT = Path({root!r})
scratch = sc.create()
toolchain = tc.resolve(ROOT, environment=tc.ENV_ALIGN, tools=tc.ROUTINE_TOOLS, scratch=scratch.root)
guard = se.install_tool_guard(
    ROOT, scratch_root=scratch.root,
    allowed_executables=frozenset(str(t.path) for t in toolchain.tools.values()),
)
"""


def run_fake(repository_root: Path, body: str) -> subprocess.CompletedProcess[str]:
    script = FAKE_PREAMBLE.format(root=str(repository_root)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=repository_root, timeout=60,
    )


def run_real(repository_root: Path, body: str) -> subprocess.CompletedProcess[str]:
    script = REAL_PREAMBLE.format(root=str(repository_root)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=repository_root, timeout=120,
    )


def assert_refused(result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"expected a refusal:\n{combined}"
    assert fragment in combined, f"expected {fragment!r} in:\n{combined}"


def assert_clean(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"expected a clean run:\n{combined}"


# --- fail-closed, no toolchain required -----------------------------------------------------------


def test_an_unknown_tool_name_is_refused(repository_root: Path) -> None:
    body = """
    runner.run_tool(
        toolchain, "clustalw", [], scratch=scratch, index=0, label="x",
        inputs={}, outputs=["out.fa"], threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "is not in the resolved toolchain")


def test_a_call_with_no_declared_output_is_refused(repository_root: Path) -> None:
    body = """
    runner.run_tool(
        toolchain, "mafft", ["--version"], scratch=scratch, index=0, label="x",
        inputs={}, outputs=[], threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "no declared output")


@pytest.mark.parametrize("bad", ["/etc/hosts", "sub/x", ".."])
def test_a_bad_argv_token_is_refused(repository_root: Path, bad: str) -> None:
    body = f"""
    runner.run_tool(
        toolchain, "mafft", [{bad!r}], scratch=scratch, index=0, label="x",
        inputs={{}}, outputs=["out.fa"], threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "argv token")


def test_a_bad_input_basename_is_refused(repository_root: Path) -> None:
    body = """
    real = fake_bin_dir / "real.fa"
    real.write_text(">a\\nAAA\\n")
    runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="x",
        inputs={"../escape.fa": real}, outputs=["out.fa"],
        threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "input basename")


def test_a_bad_output_basename_is_refused(repository_root: Path) -> None:
    body = """
    runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="x",
        inputs={}, outputs=["/etc/passwd"], threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "output basename")


def test_a_bad_stdout_to_basename_is_refused(repository_root: Path) -> None:
    body = """
    runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="x",
        inputs={}, outputs=[], stdout_to="../out.fa", threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "stdout_to basename")


def test_reusing_an_index_is_refused_by_the_underlying_scratch(repository_root: Path) -> None:
    body = """
    seed = fake_bin_dir / "seed.fa"
    seed.write_text(">a\\nAAA\\n>b\\nAAA\\n")
    runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="dup",
        inputs={"seed.fa": seed}, outputs=[], stdout_to="aln.fa",
        threads=1, timeout_s=10, guard=guard,
    )
    runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="dup",
        inputs={"seed.fa": seed}, outputs=[], stdout_to="aln.fa",
        threads=1, timeout_s=10, guard=guard,
    )
    """
    assert_refused(run_fake(repository_root, body), "already exists")


def test_run_tool_runs_clean_against_a_fake_but_well_behaved_binary(repository_root: Path) -> None:
    """The positive control for the fake-toolchain tier: a guard/runner combination that refused
    everything would fail this too, not only the refusal tests above."""
    body = """
    seed = fake_bin_dir / "seed.fa"
    seed.write_text(">a\\nAAA\\n")
    result = runner.run_tool(
        toolchain, "mafft", ["seed.fa"], scratch=scratch, index=0, label="ok",
        inputs={"seed.fa": seed}, outputs=[], stdout_to="aln.fa",
        threads=1, timeout_s=10, guard=guard,
    )
    assert result.returncode == 0
    se.assert_no_violations(guard)
    assert len(guard.execs) == 1
    print("ALL PASS")
    """
    result = run_fake(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


# --- real execution, needs the toolchain ----------------------------------------------------------


@REQUIRES_ENV
def test_a_real_seed_alignment_runs_end_to_end(repository_root: Path) -> None:
    body = """
    import tempfile
    seed = Path(tempfile.mkdtemp(dir=ROOT / ".pixi")) / "seed.fa"
    seed.write_text(">a\\nATGGCCAAGTTTGGGCCC\\n>b\\nATGGCCAAGTTTCCC\\n")

    result = runner.run_tool(
        toolchain, "mafft-linsi", ["--anysymbol", "seed.fa"],
        scratch=scratch, index=0, label="seed_align",
        inputs={"seed.fa": seed}, outputs=[], stdout_to="seed_aln.fa",
        threads=1, timeout_s=60, guard=guard,
    )
    assert result.returncode == 0
    aligned = result.stdout_path.read_text()
    assert aligned.count(">") == 2
    rows = [line for line in aligned.splitlines() if line and not line.startswith(">")]
    assert len({len(row) for row in rows}) == 1, f"aligned rows are ragged: {rows}"
    se.assert_no_violations(guard)
    assert len(guard.execs) == 1
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_two_sequential_tool_calls_run_clean(repository_root: Path) -> None:
    """The legitimate case a guard that refused everything would fail: two `run_tool` calls in
    the same build, the second consuming input the first produced."""
    body = """
    import tempfile
    seed = Path(tempfile.mkdtemp(dir=ROOT / ".pixi")) / "seed.fa"
    seed.write_text(">a\\nATGGCCAAGTTTGGGCCC\\n>b\\nATGGCCAAGTTTCCC\\n")

    first = runner.run_tool(
        toolchain, "mafft-linsi", ["--anysymbol", "seed.fa"],
        scratch=scratch, index=0, label="seed", inputs={"seed.fa": seed}, outputs=[],
        stdout_to="seed_aln.fa", threads=1, timeout_s=60, guard=guard,
    )
    second = runner.run_tool(
        toolchain, "mafft", ["--anysymbol", "seed_aln.fa"],
        scratch=scratch, index=1, label="realign",
        inputs={"seed_aln.fa": first.stdout_path}, outputs=[], stdout_to="second_aln.fa",
        threads=1, timeout_s=30, guard=guard,
    )
    assert first.returncode == 0
    assert second.returncode == 0
    se.assert_no_violations(guard)
    assert len(guard.execs) == 2
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_a_nonzero_exit_is_refused_with_stderr_in_the_message(repository_root: Path) -> None:
    body = """
    runner.run_tool(
        toolchain, "mafft-linsi", ["--anysymbol", "nope.fa"],
        scratch=scratch, index=0, label="broken",
        inputs={}, outputs=[], stdout_to="out.fa",
        threads=1, timeout_s=30, guard=guard,
    )
    """
    assert_refused(run_real(repository_root, body), "exited")


@REQUIRES_ENV
def test_a_missing_declared_output_is_refused(repository_root: Path) -> None:
    """`cmalign -h` exits 0 and writes nothing to disk; declaring a file output for it must fail."""
    body = """
    runner.run_tool(
        toolchain, "cmalign", ["-h"], scratch=scratch, index=0, label="no_output",
        inputs={}, outputs=["nonexistent.sto"], threads=1, timeout_s=30, guard=guard,
    )
    """
    assert_refused(run_real(repository_root, body), "did not produce declared output")
