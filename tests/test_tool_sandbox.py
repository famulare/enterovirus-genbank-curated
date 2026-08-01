"""Falsification tests for the tool-exec guard.

Same discipline as `tests/test_sandbox.py`: a guard only ever observed to pass is not evidence of
anything, so every rule this guard claims to enforce is planted here as a deliberate violation and
asserted to fail. Each case runs in its own interpreter, for the same reason — the hook cannot be
uninstalled.

Positive controls matter at least as much as the refusals here, because this guard's entire point
is that it must still let a *legitimate* call through — a guard that refused everything would pass
every test below except the ones in the last section.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)

PREAMBLE = """
import subprocess
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import toolchain as tc

ROOT = Path({root!r})
SCRATCH = Path({scratch!r})
RUN_DIR = Path({run_dir!r})
MAFFT = {mafft!r}
resolved = tc.resolve(ROOT, environment=tc.ENV_ALIGN, tools=tc.ROUTINE_TOOLS, scratch=SCRATCH)
ENV = {{
    "PATH": resolved.child_path(), "HOME": str(RUN_DIR), "TMPDIR": str(RUN_DIR), "LC_ALL": "C",
    "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
}}
guard = se.install_tool_guard(ROOT, scratch_root=SCRATCH, allowed_executables=frozenset({{MAFFT}}))
"""


@pytest.fixture
def scratch_dirs(tmp_path_factory) -> tuple[Path, Path]:
    """A real `mkdtemp`-style scratch tree and a run dir inside it — required by
    `install_tool_guard`, which refuses a `scratch_root` outside the default scratch tree."""
    scratch = Path(tempfile.mkdtemp())
    run_dir = scratch / "0000-test"
    run_dir.mkdir()
    return scratch, run_dir


def run_guarded(
    repository_root: Path, scratch: Path, run_dir: Path, body: str
) -> subprocess.CompletedProcess[str]:
    mafft = str(repository_root / ".pixi/envs/align/bin/mafft")
    script = PREAMBLE.format(
        root=str(repository_root), scratch=str(scratch), run_dir=str(run_dir), mafft=mafft
    ) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=repository_root, timeout=120,
    )


def assert_blocked(result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"the violation was allowed through:\n{combined}"
    assert "ToolExecError" in combined, combined
    assert fragment in combined, f"expected {fragment!r} in:\n{combined}"


def assert_clean(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"expected a clean run:\n{combined}"


# --- positive controls: a legitimate call must still work ---------------------------------------


@REQUIRES_ENV
def test_the_real_pinned_toolchain_runs_clean(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    result = subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    se.assert_no_violations(guard)
    assert len(guard.execs) == 1, guard.execs
    print("ALL PASS")
    """
    result = run_guarded(repository_root, scratch, run_dir, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_a_legitimate_two_step_pipeline_runs_clean(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """A guard that refused everything would fail this, not just the refusal tests."""
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    r1 = subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV,
                        capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    se.arm(guard)
    r2 = subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV,
                        capture_output=True, text=True)
    assert r2.returncode == 0, r2.stderr
    se.assert_no_violations(guard)
    assert len(guard.execs) == 2, guard.execs
    print("ALL PASS")
    """
    result = run_guarded(repository_root, scratch, run_dir, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


# --- the allowlist and the arm token --------------------------------------------------------------


@REQUIRES_ENV
def test_an_unallowlisted_binary_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """Argv with no risky tokens, so this isolates the allowlist rule rather than the argv rule —
    a single-element argv (`/bin/cat`'s absolute path is the *executable*, checked by the
    allowlist, not by the argv rule, which only inspects `argv[1:]`)."""
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run(["/bin/cat"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "not in the allowlisted")


def test_shell_true_is_refused(repository_root: Path, scratch_dirs: tuple[Path, Path]) -> None:
    """`/bin/sh` is not allowlisted, so `shell=True` is refused for free.

    The shell string is deliberately slash-free (`id`, not `cat /etc/hosts`): a slash anywhere in
    the string would trip the argv rule first (the whole string is one `argv[1]` token after
    `shell=True` rewrites it to `['/bin/sh', '-c', string]`), which would still prove the child is
    refused but for the wrong stated reason.
    """
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run("id", shell=True, cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "not in the allowlisted")


@REQUIRES_ENV
def test_an_allowlisted_binary_outside_an_armed_window_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """A perfectly legal cwd and env, but never armed. Kills the allowlist check alone."""
    scratch, run_dir = scratch_dirs
    body = """
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(
        run_guarded(repository_root, scratch, run_dir, body), "outside an armed run_tool"
    )


@REQUIRES_ENV
def test_the_arm_token_is_one_shot(repository_root: Path, scratch_dirs: tuple[Path, Path]) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    r1 = subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV,
                        capture_output=True, text=True)
    assert r1.returncode == 0, r1.stderr
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(
        run_guarded(repository_root, scratch, run_dir, body), "outside an armed run_tool"
    )


@REQUIRES_ENV
def test_a_failed_armed_call_still_consumes_the_token(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """The one-shot property must hold on the failure path too — see the module docstring."""
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    try:
        subprocess.run(["/bin/cat"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    except Exception:
        pass
    # Token should be consumed even though the first call failed; this second, otherwise-legitimate
    # call must still be refused as unarmed.
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(
        run_guarded(repository_root, scratch, run_dir, body), "outside an armed run_tool"
    )


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed",
)
def test_a_symlink_to_an_unallowlisted_binary_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path], tmp_path: Path
) -> None:
    """Resolution happens before the allowlist decision, so a symlink cannot alias an allowed name
    onto a disallowed target — same reasoning as `sandbox._within`'s."""
    scratch, run_dir = scratch_dirs
    shim_dir = tmp_path / "shim"
    shim_dir.mkdir()
    shim = shim_dir / "mafft"
    shim.symlink_to("/bin/cat")
    body = f"""
    se.arm(guard)
    subprocess.run([{str(shim)!r}, "-h"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "not in the allowlisted")


# --- child narrowing: env, cwd, argv --------------------------------------------------------------


@REQUIRES_ENV
def test_an_inherited_environment_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "do not exactly match")


@REQUIRES_ENV
def test_an_extra_environment_key_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    env = dict(ENV, LD_PRELOAD="/tmp/evil.so")
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=env, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "do not exactly match")


@REQUIRES_ENV
def test_a_missing_environment_key_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """The other direction of exact equality: a subset must fail too, not only a superset."""
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    env = dict(ENV)
    del env["LC_ALL"]
    subprocess.run([MAFFT, "--version"], cwd=str(RUN_DIR), env=env, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "do not exactly match")


@REQUIRES_ENV
def test_a_cwd_outside_scratch_is_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run([MAFFT, "--version"], cwd=str(ROOT), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(
        run_guarded(repository_root, scratch, run_dir, body),
        "is not inside the declared scratch directory",
    )


@REQUIRES_ENV
def test_argv_may_not_contain_an_absolute_path(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run([MAFFT, "/etc/hosts"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    assert guard.execs == [], guard.execs
    """
    result = run_guarded(repository_root, scratch, run_dir, body)
    assert_blocked(result, "not a bare filename")


@REQUIRES_ENV
def test_argv_may_not_contain_a_path_separator(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run([MAFFT, "sub/x"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "not a bare filename")


@REQUIRES_ENV
def test_argv_may_not_contain_dotdot(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    subprocess.run([MAFFT, "..", "x"], cwd=str(RUN_DIR), env=ENV, capture_output=True, text=True)
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "not a bare filename")


# --- rules inherited from the input guard, re-asserted under the weaker one ----------------------


def test_os_system_is_still_refused(repository_root: Path, scratch_dirs: tuple[Path, Path]) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    import os
    os.system("cat /etc/hosts")
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "refused unconditionally")


def test_a_bare_fork_is_still_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    import os
    os.fork()
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "refused unconditionally")


def test_network_is_still_refused(repository_root: Path, scratch_dirs: tuple[Path, Path]) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    import socket
    socket.create_connection(("example.com", 80), timeout=1)
    """
    assert_blocked(
        run_guarded(repository_root, scratch, run_dir, body), "not a declared input"
    )


def test_writing_into_raw_is_still_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    """`final/` left the immutable set on 2026-08-01; `raw/`, the frozen input, did not."""
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    (ROOT / "raw" / "__tool_guard_probe__").write_text("x")
    """
    result = run_guarded(repository_root, scratch, run_dir, body)
    probe = repository_root / "raw" / "__tool_guard_probe__"
    try:
        assert_blocked(result, "immutable release tree")
    finally:
        probe.unlink(missing_ok=True)


def test_reading_registry_legacy_is_still_refused(
    repository_root: Path, scratch_dirs: tuple[Path, Path]
) -> None:
    scratch, run_dir = scratch_dirs
    body = """
    se.arm(guard)
    next((ROOT / "registry" / "legacy").glob("*")).read_bytes()
    """
    assert_blocked(run_guarded(repository_root, scratch, run_dir, body), "read by nothing")


# --- scratch_root containment ---------------------------------------------------------------------


def test_a_scratch_root_outside_the_default_tree_is_refused(repository_root: Path) -> None:
    # Deliberately not using the fixture: this test needs a scratch_root that is NOT under the
    # default temp tree, which install_tool_guard must refuse before installing anything.
    script = f"""
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
se.install_tool_guard(
    Path({str(repository_root)!r}), scratch_root=Path({str(repository_root)!r}) / "final",
    allowed_executables=frozenset(),
)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=repository_root, timeout=30,
    )
    combined = result.stdout + result.stderr
    assert result.returncode != 0
    assert "ToolExecError" in combined
    assert "not inside the default scratch tree" in combined
