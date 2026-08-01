"""Falsification tests for the undeclared-input guard.

A guard that has only ever been observed to pass is not evidence of anything — that is the lesson
this repository keeps relearning (a self-certifying parity oracle in stage 1, a parity check that
compared a rebuild against bytes it could itself overwrite in stage 3, a parity gate projected onto
three of fourteen columns in stage 2). So every rule the guard claims to enforce is planted here as
a deliberate violation and asserted to fail.

The hook cannot be uninstalled, so each case runs in its own interpreter.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import uuid
from pathlib import Path

import pytest

PREAMBLE = """
from pathlib import Path
from enterovirus_genbank_curated.sandbox import (
    UndeclaredInputError, assert_no_violations, install_input_guard,
)
ROOT = Path({root!r})
guard = install_input_guard(ROOT)
"""


def run_guarded(root: Path, body: str) -> subprocess.CompletedProcess[str]:
    script = PREAMBLE.format(root=str(root)) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=root, timeout=120,
    )


def assert_blocked(result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"the violation was allowed through:\n{combined}"
    assert "UndeclaredInputError" in combined, combined
    assert fragment in combined, f"expected {fragment!r} in:\n{combined}"


# --- reads outside the clone -------------------------------------------------------------------


def test_reading_an_out_of_clone_path_fails(repository_root: Path) -> None:
    assert_blocked(run_guarded(repository_root, "open('/etc/hosts').read()"), "undeclared path")


def test_reading_a_home_directory_path_fails(repository_root: Path) -> None:
    body = "open(str(Path.home() / 'notes.txt')).read()"
    assert_blocked(run_guarded(repository_root, body), "undeclared path")


def test_a_nonexistent_out_of_clone_path_still_fails(repository_root: Path) -> None:
    """The guard must catch the *attempt*. Waiting for a successful read would mean a build that
    silently depended on a sibling repo passed on any machine where that repo was missing."""
    body = "open('/etc/no-such-file-fbc21d').read()"
    assert_blocked(run_guarded(repository_root, body), "undeclared path")


def test_the_private_source_repository_is_not_readable(repository_root: Path) -> None:
    """The specific failure this exists to prevent: quietly reading MAD-VDPV again."""
    body = "open(str(ROOT.parent / 'MAD-VDPV' / 'data' / 'genbank' / 'working' / 'x.csv')).read()"
    assert_blocked(run_guarded(repository_root, body), "undeclared path")


def test_os_open_is_guarded_too(repository_root: Path) -> None:
    """`os.open` raises the same audit event with an int flag rather than a mode string."""
    body = "import os; os.open('/etc/hosts', os.O_RDONLY)"
    assert_blocked(run_guarded(repository_root, body), "undeclared path")


# --- writes ------------------------------------------------------------------------------------
#
# These probes open for writing, which *creates* the file, so they are only non-destructive while
# the guard works — the property under test. A regression therefore used to leave real debris: a
# 1-byte `final/planted-violation` appeared in the shipped release tree during a review's planted-
# mutation battery. `assert_absent` makes that outcome a loud failure and cleans up regardless, so a
# broken guard cannot quietly mutate the parity oracle through its own test suite.


@pytest.fixture
def probe_name() -> str:
    """A filename this test run alone can have created.

    Deliberately not a fixed name like `planted-violation`. A fixed name means the cleanup cannot
    distinguish debris it just made from a file that was already there, so it either leaves real
    debris behind or deletes something it did not create. A stale `~/planted-violation` from an
    earlier battery was in fact found this way. With a nonce, absence afterwards is proof about
    *this* run and the unlink can never touch anything else.
    """
    return f"evgc-guard-probe-{uuid.uuid4().hex[:12]}"


def assert_absent(target: Path) -> None:
    try:
        assert not target.exists(), (
            f"the guard let a write through and {target} now exists. It has been removed, but "
            f"check `git status` — if this is under final/ or raw/, the immutable release tree was "
            f"modified by the test suite."
        )
    finally:
        target.unlink(missing_ok=True)


def test_writing_into_final_is_allowed_now(repository_root: Path, probe_name: str) -> None:
    """The inverse of what this asserted until 2026-08-01: `final/` is the build's destination.

    Kept as a positive control rather than deleted. The write rule and the read rule for `final/`
    used to be one decision; they are now two, and the read refusal below is the one that carries
    the property. A test that only checked the refusal would pass just as well if the guard had
    been switched off entirely for that tree.
    """
    target = repository_root / "final" / probe_name
    try:
        body = textwrap.dedent(f"""
            open(str(ROOT / 'final' / {probe_name!r}), 'w').write('x')
            assert_no_violations(guard)
            print('OK')
        """)
        result = run_guarded(repository_root, body)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout
        # The probe is expected to exist here — that is the point — so it is removed rather than
        # asserted absent. `assert_absent` is for the refusal tests, where a surviving file is the
        # failure.
        assert target.is_file()
    finally:
        target.unlink(missing_ok=True)


def test_writing_into_raw_fails(repository_root: Path, probe_name: str) -> None:
    target = repository_root / "raw" / probe_name
    try:
        body = f"open(str(ROOT / 'raw' / {probe_name!r}), 'w').write('x')"
        assert_blocked(run_guarded(repository_root, body), "immutable release tree")
    finally:
        assert_absent(target)


def test_writing_outside_the_clone_fails(repository_root: Path, probe_name: str) -> None:
    target = Path.home() / probe_name
    try:
        body = f"open(str(Path.home() / {probe_name!r}), 'w').write('x')"
        assert_blocked(run_guarded(repository_root, body), "write outside the clone")
    finally:
        assert_absent(target)


# --- symlink aliasing ----------------------------------------------------------------------------
#
# `_within` used to compare the literal path first and consult `realpath` only as a fallback, so
# resolution could only widen the allowlist. A symlink sitting inside an allowed root was admitted
# without its target being examined: `$TMPDIR/shim -> /etc/hosts` read outside the clone and a
# symlink into `$HOME` wrote there, both with zero violations and a clean PASS. The realistic form
# is a developer symlinking `raw/sequence.gb.zip` at a copy in `~/Downloads`.


def test_a_symlink_inside_scratch_cannot_read_outside_the_clone(repository_root: Path) -> None:
    body = textwrap.dedent("""
        import os, tempfile
        shim = os.path.join(tempfile.gettempdir(), 'evgc-test-rshim')
        if os.path.islink(shim) or os.path.exists(shim):
            os.remove(shim)
        os.symlink('/etc/hosts', shim)
        try:
            open(shim).read()
        finally:
            os.remove(shim)
    """)
    assert_blocked(run_guarded(repository_root, body), "undeclared path")


def test_a_symlink_inside_scratch_cannot_write_outside_the_clone(
    repository_root: Path, probe_name: str
) -> None:
    target = Path.home() / probe_name
    try:
        body = textwrap.dedent(f"""
            import os, tempfile
            from pathlib import Path
            shim = os.path.join(tempfile.gettempdir(), {probe_name + "-wshim"!r})
            os.symlink(str(Path.home() / {probe_name!r}), shim)
            try:
                open(shim, 'w').write('x')
            finally:
                os.remove(shim)
        """)
        assert_blocked(run_guarded(repository_root, body), "write outside the clone")
    finally:
        assert_absent(target)


def test_a_symlink_into_the_raw_tree_cannot_be_written(
    repository_root: Path, probe_name: str
) -> None:
    """The immutable-tree rule has to survive aliasing too, not just the clone boundary."""
    target = repository_root / "raw" / probe_name
    try:
        body = textwrap.dedent(f"""
            import os, tempfile
            shim = os.path.join(tempfile.gettempdir(), {probe_name + "-fshim"!r})
            os.symlink(str(ROOT / 'raw' / {probe_name!r}), shim)
            try:
                open(shim, 'w').write('x')
            finally:
                os.remove(shim)
        """)
        assert_blocked(run_guarded(repository_root, body), "immutable release tree")
    finally:
        assert_absent(target)


def test_a_symlink_to_an_allowed_path_is_still_allowed(repository_root: Path) -> None:
    """Negative control. Resolving before the decision must not reject legitimate aliasing, or the
    three tests above would pass by refusing everything."""
    body = textwrap.dedent("""
        import os, tempfile
        shim = os.path.join(tempfile.gettempdir(), 'evgc-test-okshim')
        if os.path.islink(shim) or os.path.exists(shim):
            os.remove(shim)
        os.symlink(str(ROOT / 'registry' / 'decisions.tsv'), shim)
        try:
            open(shim).readline()
            assert_no_violations(guard)
            print('OK')
        finally:
            os.remove(shim)
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# --- network -----------------------------------------------------------------------------------


def test_dns_resolution_fails(repository_root: Path) -> None:
    body = "import socket; socket.getaddrinfo('example.invalid', 80)"
    assert_blocked(run_guarded(repository_root, body), "network access")


def test_opening_a_socket_connection_fails(repository_root: Path) -> None:
    body = textwrap.dedent("""
        import socket
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(('127.0.0.1', 9))
    """)
    assert_blocked(run_guarded(repository_root, body), "network access")


def test_a_subprocess_cannot_be_used_to_escape(repository_root: Path) -> None:
    body = "import subprocess; subprocess.run(['cat', '/etc/hosts'])"
    assert_blocked(run_guarded(repository_root, body), "escape the guard")


def test_a_real_aligner_binary_is_still_refused(repository_root: Path) -> None:
    """The regression this refactor exists to rule out: `_path_rule_set` must not have widened
    anything for the tool-exec guard's benefit. A real `mafft` invocation is refused exactly like
    any other subprocess, by an absolute path this time rather than a bare name on PATH."""
    mafft = repository_root / ".pixi" / "envs" / "align" / "bin" / "mafft"
    if not mafft.is_file():
        pytest.skip("pixi align environment is not installed")
    body = f"import subprocess; subprocess.run([{str(mafft)!r}, '--version'])"
    assert_blocked(run_guarded(repository_root, body), "escape the guard")


# Until 2026-07-29 only `subprocess.Popen` was covered, so the three cases below all ran a child
# process that read whatever it liked while the guard reported a clean build. `os.system` is the
# shortest way to shell out to an aligner, which is exactly what the next pipeline stage needs.
def test_os_system_cannot_be_used_to_escape(repository_root: Path) -> None:
    body = "import os; os.system('cat /etc/hosts')"
    assert_blocked(run_guarded(repository_root, body), "escape the guard")


def test_os_spawn_cannot_be_used_to_escape(repository_root: Path) -> None:
    body = "import os; os.spawnl(os.P_WAIT, '/bin/cat', '/bin/cat', '/etc/hosts')"
    assert_blocked(run_guarded(repository_root, body), "escape the guard")


def test_a_bare_fork_cannot_be_used_to_escape(repository_root: Path) -> None:
    """`os.fork` is what closes the family: on POSIX `os.spawnl` is fork+exec in Python and raises
    only this event, so subscribing to it covers spawn variants and `multiprocessing` too."""
    body = "import os; os.fork()"
    assert_blocked(run_guarded(repository_root, body), "escape the guard")


# --- filesystem mutations that never reach the `open` event ---------------------------------------
#
# Every one of these was invisible to the guard before 2026-07-29, which made the documented "no
# write into final/" guarantee false. The probes target paths that do not exist, so the syscall
# fails on its own; what is under test is whether the guard sees the attempt at all.


def test_removing_a_file_from_the_immutable_tree_is_refused(repository_root: Path) -> None:
    body = "import os; os.remove(str(ROOT / 'raw' / 'probe-absent'))"
    assert_blocked(run_guarded(repository_root, body), "immutable release tree")


def test_atomically_replacing_a_released_artifact_is_refused(repository_root: Path) -> None:
    """The realistic failure: publishing an artifact by writing to scratch and renaming into place.

    The write to scratch is legitimate, so the rename is the only thing that can catch it. The
    source therefore has to be a genuinely allowed path — `tempfile.gettempdir()`, not `/tmp`, which
    is outside the write roots on macOS — or the source trips first and this stops testing the
    destination check.
    """
    body = textwrap.dedent("""
        import os, tempfile
        source = os.path.join(tempfile.gettempdir(), 'probe-absent')
        os.replace(source, str(ROOT / 'raw' / 'sequence.gb.zip'))
    """)
    assert_blocked(run_guarded(repository_root, body), "immutable release tree")


def test_renaming_out_of_the_clone_is_refused(repository_root: Path) -> None:
    body = "import os; os.rename(str(ROOT / 'probe-absent'), str(Path.home() / 'probe-absent'))"
    assert_blocked(run_guarded(repository_root, body), "outside the clone")


def test_creating_a_directory_in_the_raw_tree_is_refused(repository_root: Path) -> None:
    body = "import os; os.mkdir(str(ROOT / 'raw' / 'probe-absent'))"
    assert_blocked(run_guarded(repository_root, body), "immutable release tree")


def test_truncating_a_released_artifact_is_refused(repository_root: Path) -> None:
    body = "import os; os.truncate(str(ROOT / 'raw' / 'probe-absent'), 0)"
    assert_blocked(run_guarded(repository_root, body), "immutable release tree")


def test_symlinking_outside_the_clone_is_refused(repository_root: Path) -> None:
    body = "import os; os.symlink('/etc/hosts', str(Path.home() / 'probe-absent-link'))"
    assert_blocked(run_guarded(repository_root, body), "outside the clone")


def test_recursively_deleting_a_released_tree_is_refused(repository_root: Path) -> None:
    body = "import shutil; shutil.rmtree(str(ROOT / 'raw' / 'probe-absent'))"
    assert_blocked(run_guarded(repository_root, body), "immutable release tree")


def test_mutating_the_scratch_directory_is_still_allowed(repository_root: Path) -> None:
    """Negative control. A guard that refused every mutation would make the seven tests above pass
    vacuously and would also break the build, which writes to scratch."""
    body = textwrap.dedent("""
        import os, tempfile
        scratch = tempfile.mkdtemp()
        target = os.path.join(scratch, 'probe')
        open(target, 'w').write('x')
        os.rename(target, target + '-renamed')
        os.remove(target + '-renamed')
        os.rmdir(scratch)
        assert_no_violations(guard)
        print('OK')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


# --- the recorded-violation backstop -------------------------------------------------------------


def test_a_swallowed_exception_still_fails_the_build(repository_root: Path) -> None:
    """Raising alone is not enough, because a caller can catch it.

    `UndeclaredInputError` is a `ContractError`, not an `OSError`, so ordinary I/O error handling
    does not swallow it — but a bare `except` does, and that is a real idiom in cleanup paths. The
    violation is therefore also recorded, and `assert_no_violations` re-checks the record after the
    build. (This docstring used to cite `Path.exists()`, which does not reach the hook at all; see
    `test_the_stat_family_is_a_known_hole_and_is_asserted_as_one`.)
    """
    body = textwrap.dedent("""
        try:
            open('/etc/hosts').read()
        except BaseException:
            pass
        print('the raise was swallowed, as intended by this test')
        assert_no_violations(guard)
    """)
    result = run_guarded(repository_root, body)
    assert "the raise was swallowed" in result.stdout
    assert_blocked(result, "touched 1 undeclared input")


def test_the_stat_family_is_a_known_hole_and_is_asserted_as_one(repository_root: Path) -> None:
    """Existence probes are **not** caught, and that is pinned so the docs cannot drift back.

    This replaced a test that asserted the opposite. It wrapped its only assertion in
    `if result.returncode != 0:` and the observed return code is 0, so it executed no assertion at
    all — a test that could not fail, standing in for a guarantee the guard does not provide. The
    module docstring and `docs/reproducibility.md` both claimed `Path.exists()` was covered on the
    strength of it.

    Stating the hole as an expectation means that if a future Python starts raising an audit event
    for the stat family, or the guard subscribes to one, this fails and the documented limits get
    revisited deliberately.
    """
    body = textwrap.dedent("""
        import os
        Path('/etc/hosts').exists()
        os.stat('/etc/hosts')
        os.listdir(str(Path.home()))
        assert_no_violations(guard)
        print(f'UNSEEN {len(guard.violations)}')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, (
        "the stat family now trips the guard. That is an improvement, not a failure — but "
        "docs/reproducibility.md and sandbox.py both document it as a gap, so update them and "
        "this test together."
    )
    assert "UNSEEN 0" in result.stdout, result.stdout + result.stderr


# --- the guard must not fire on legitimate work --------------------------------------------------


def test_reading_inside_the_clone_is_allowed(repository_root: Path) -> None:
    body = textwrap.dedent("""
        open(str(ROOT / 'registry' / 'decisions.tsv')).readline()
        assert_no_violations(guard)
        print('OK')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_reading_the_shipped_release_is_refused(repository_root: Path) -> None:
    """A guarded build may not read a `final/` file it did not itself write.

    This is the half of the old `final/` rule that carried the property, and it outlived the write
    refusal. Refusing only *writes* left the failure that matters wide open: a derive stage that
    reads the previous canonical table can reproduce it perfectly and prove nothing, and
    calibrating a rule against the last release is exactly when someone reaches for that read.

    `build_manifest.json` is the right probe precisely because the build also *writes* a file by
    that name: reading the one already on disk, before this run has written it, is the read being
    refused.
    """
    body = textwrap.dedent("""
        open(str(ROOT / 'final' / 'audit' / 'build_manifest.json')).read()
        print('NOT REACHED')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode != 0
    assert "never a pipeline input" in result.stderr


def test_reading_the_frozen_raw_archive_is_still_allowed(repository_root: Path) -> None:
    """The negative control for the rule above: `raw/` is immutable but it is a declared input.

    Without this, a guard that refused both immutable trees would pass the refusal test while making
    every build impossible.
    """
    body = textwrap.dedent("""
        open(str(ROOT / 'raw' / 'raw_manifest.json')).read()
        assert_no_violations(guard)
        print('OK')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr


def test_scratch_space_is_allowed(repository_root: Path) -> None:
    body = textwrap.dedent("""
        import tempfile
        with tempfile.TemporaryDirectory() as scratch:
            (Path(scratch) / 'x').write_text('x')
        assert_no_violations(guard)
        print('OK')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr


def test_importing_third_party_packages_is_allowed(repository_root: Path) -> None:
    """Biopython and DuckDB live in site-packages, outside the clone."""
    body = textwrap.dedent("""
        import Bio.SeqIO, duckdb  # noqa: F401
        duckdb.connect(':memory:').execute('select 1').fetchall()
        assert_no_violations(guard)
        print('OK')
    """)
    result = run_guarded(repository_root, body)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.slow
def test_the_real_source_build_runs_clean_under_the_guard(repository_root: Path) -> None:
    """The claim in `docs/reproducibility.md`, executed: the whole source layer regenerates and
    byte-matches the release without touching anything outside the clone."""
    result = subprocess.run(
        [sys.executable, "-m", "enterovirus_genbank_curated.cli",
         "parity-source", "--guard-inputs", "--repository-root", str(repository_root)],
        capture_output=True, text=True, cwd=repository_root, timeout=1800,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "source parity: PASS" in result.stdout, combined
    assert "undeclared-input guard: PASS" in result.stdout, combined
