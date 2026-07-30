"""The native aligners must be the ones `registry/toolchain.json` and `pixi.lock` declare.

Upstream recorded no tool version in any provenance file, so a `pixi update` there could change
alignment output with nothing to notice. These tests pin the two-sided check that replaces that gap:
`conda-meta` for what was installed, and the binary's own self-report for what is actually being
run. Either alone is satisfiable by a lie.

Tests that need the environment skip when it is absent, and `test_ci_has_the_toolchain` fails when
`CI=true` and it is missing — so the skips cannot quietly hide the whole file.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import toolchain as tc

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)
REQUIRES_SEED_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/seed/bin/mafft-xinsi").exists(),
    reason="pixi seed environment is not installed; run `pixi install --locked -e seed`",
)
REQUIRES_MXSCARNAMOD = pytest.mark.skipif(
    not (
        Path(__file__).resolve().parents[1] / ".pixi/envs/seed/libexec/mafft/mxscarnamod"
    ).exists(),
    reason="mxscarnamod is not built; run scripts/setup_mxscarna.sh (network + a C++ compiler, "
    "not expected on a fresh clone)",
)


@pytest.fixture(scope="module")
def scratch(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("toolchain")


@pytest.fixture(scope="module")
def resolved(repository_root: Path, scratch: Path) -> tc.Toolchain:
    return tc.resolve(repository_root, scratch=scratch)


# --- the declaration, checkable with no environment ---------------------------------------------


def test_the_declaration_matches_the_committed_lock(repository_root: Path) -> None:
    """A lock change must invalidate the declaration; otherwise the pins are decorative."""
    declaration = tc.load_declaration(repository_root)
    assert declaration["pixi_lock_sha256"] == tc.lock_sha256(repository_root)


def test_the_declaration_covers_both_platforms(repository_root: Path) -> None:
    """CI runs linux-64 and the author runs osx-arm64. A one-platform declaration gates nothing."""
    declaration = tc.load_declaration(repository_root)
    assert set(declaration["platforms"]) == {"linux-64", "osx-arm64"}
    for platform, environments in declaration["platforms"].items():
        assert tc.ENV_ALIGN in environments, f"{platform} declares no {tc.ENV_ALIGN} environment"


def test_the_declaration_names_every_package_the_routine_tier_needs(
    repository_root: Path,
) -> None:
    """Derived from PROBES by union, never hand-listed — the B7 lesson about completeness."""
    needed = {tc.PROBES[name].package for name in tc.ROUTINE_TOOLS}
    declaration = tc.load_declaration(repository_root)
    for platform, environments in declaration["platforms"].items():
        declared = set(environments[tc.ENV_ALIGN])
        assert declared == needed, f"{platform}: declared {declared}, need {needed}"


def test_the_build_strings_differ_across_platforms(repository_root: Path) -> None:
    """Same version, different conda build. Equal build strings would mean the lock was not
    re-solved for the second platform, which is how upstream's osx-only lock looked."""
    platforms = tc.load_declaration(repository_root)["platforms"]
    linux = platforms["linux-64"][tc.ENV_ALIGN]
    osx = platforms["osx-arm64"][tc.ENV_ALIGN]
    for package in linux:
        assert linux[package]["version"] == osx[package]["version"], package
        assert linux[package]["build"] != osx[package]["build"], package


def test_the_canonical_platform_is_the_one_ci_runs(repository_root: Path) -> None:
    declaration = tc.load_declaration(repository_root)
    assert declaration["canonical_platform"] == tc.CANONICAL_PLATFORM == "linux-64"
    workflow = (repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-latest" in workflow


def test_the_lock_reader_recovers_the_declared_linux_versions(repository_root: Path) -> None:
    """The lock-derived half of the declaration must actually come from the lock."""
    declared = tc.load_declaration(repository_root)["platforms"]["linux-64"][tc.ENV_ALIGN]
    from_lock = tc.packages_from_lock(
        repository_root, tc.ENV_ALIGN, "linux-64", tuple(sorted(declared))
    )
    assert from_lock == declared


def test_a_missing_platform_in_the_lock_is_refused(repository_root: Path) -> None:
    with pytest.raises(tc.ToolchainError, match="does not cover"):
        tc.packages_from_lock(repository_root, tc.ENV_ALIGN, "win-64", ("mafft",))


def test_a_package_absent_from_the_lock_is_refused(repository_root: Path) -> None:
    with pytest.raises(tc.ToolchainError, match="does not resolve"):
        tc.packages_from_lock(repository_root, tc.ENV_ALIGN, "linux-64", ("clustalw",))


def test_the_seed_environment_is_not_in_the_align_lock_block(repository_root: Path) -> None:
    """viennarna must not have leaked into the environment the build runs in."""
    with pytest.raises(tc.ToolchainError, match="does not resolve"):
        tc.packages_from_lock(repository_root, tc.ENV_ALIGN, "osx-arm64", ("viennarna",))


# --- resolution against the live environment ----------------------------------------------------


@REQUIRES_ENV
def test_the_live_toolchain_matches_the_declaration(
    repository_root: Path, resolved: tc.Toolchain
) -> None:
    tc.assert_declared(repository_root, resolved)


@REQUIRES_ENV
def test_every_binary_resolves_inside_the_clone(
    repository_root: Path, resolved: tc.Toolchain
) -> None:
    """The property that keeps this stage inside `sandbox.py`'s existing read roots.

    Measured to hold because rattler hardlinks rather than symlinking into a cache under `$HOME`. If
    it ever stops holding, the root-vs-nested pixi decision and the zero-widening claim both need
    revisiting — which is why this is a test and not a comment.
    """
    root = str(repository_root.resolve()) + os.sep
    for name, tool in resolved.tools.items():
        assert str(Path(os.path.realpath(tool.path))).startswith(root), name


@REQUIRES_ENV
def test_the_self_report_agrees_with_conda_meta(resolved: tc.Toolchain) -> None:
    """The cross-check that catches a PATH pointing somewhere other than the inspected prefix."""
    for name, tool in resolved.tools.items():
        assert tool.version in tool.self_reported or tool.version.rsplit(".", 1)[0] in (
            tool.self_reported
        ), f"{name}: {tool.self_reported!r} does not carry {tool.version}"


@REQUIRES_ENV
def test_mafft_reports_its_version_on_stderr_and_exits_zero(resolved: tc.Toolchain) -> None:
    """A measured quirk, asserted so a future mafft that changes it fails loudly.

    An earlier design assumed `mafft --version` exits nonzero and a probe table built on that would
    have reported a working mafft as missing. It exits 0 and writes to stderr, so the probe asserts
    no exit code and searches both streams.
    """
    import subprocess

    tool = resolved.tools["mafft"]
    result = subprocess.run(
        [str(tool.path), "--version"],
        capture_output=True,
        text=True,
        env={"PATH": resolved.child_path(), "HOME": "/tmp", "LC_ALL": "C"},
        cwd="/tmp",
        timeout=60,
    )
    assert result.returncode == 0
    assert "v7." in result.stderr
    assert "v7." not in result.stdout


@REQUIRES_ENV
def test_infernal_reports_its_version_on_stdout(resolved: tc.Toolchain) -> None:
    import subprocess

    tool = resolved.tools["cmalign"]
    result = subprocess.run(
        [str(tool.path), "-h"],
        capture_output=True,
        text=True,
        env={"PATH": resolved.child_path(), "HOME": "/tmp", "LC_ALL": "C"},
        cwd="/tmp",
        timeout=60,
    )
    assert "INFERNAL" in result.stdout


@REQUIRES_ENV
def test_the_child_path_is_a_prefix_not_a_replacement(resolved: tc.Toolchain) -> None:
    """`PATH=<prefix>/bin` alone breaks mafft: its conda package declares only gawk, so the prefix
    has no dirname, basename, uname or grep, and mafft's entry points are shell scripts needing all
    four. Measured by running it with `env -i` and watching each failure in turn."""
    parts = resolved.child_path().split(os.pathsep)
    assert parts[0] == str(resolved.bin_dir)
    assert parts[1:] == list(tc.SYSTEM_PATH_SUFFIX)


@REQUIRES_ENV
def test_mafft_actually_aligns_under_the_declared_child_environment(
    resolved: tc.Toolchain, scratch: Path
) -> None:
    """A positive control. A toolchain check that only ever refused things would pass vacuously."""
    import subprocess

    fasta = scratch / "pair.fa"
    fasta.write_text(">a\nATGGCCAAGTTTGGGCCC\n>b\nATGGCCAAGTTTCCC\n", encoding="utf-8")
    result = subprocess.run(
        [str(resolved.tools["mafft"].path), "--quiet", fasta.name],
        capture_output=True,
        text=True,
        env={
            "PATH": resolved.child_path(),
            "HOME": str(scratch),
            "TMPDIR": str(scratch),
            "LC_ALL": "C",
        },
        cwd=str(scratch),
        timeout=120,
    )
    assert result.returncode == 0, result.stderr[-500:]
    assert result.stdout.count(">") == 2
    widths = {
        len(block.replace("\n", ""))
        for block in result.stdout.split(">")[1:]
        for block in [block.split("\n", 1)[1]]
    }
    assert len(widths) == 1, f"aligned rows are ragged: {widths}"


# --- the seed tier: mafft-xinsi, RNAalifold, cmbuild, and the mxscarnamod it needs ---------------


@pytest.fixture(scope="module")
def resolved_seed(repository_root: Path, scratch: Path) -> tc.Toolchain:
    return tc.resolve(
        repository_root, environment=tc.ENV_SEED, tools=tc.SEED_TOOLS, scratch=scratch
    )


def test_the_seed_tools_are_upstreams_required_tools_exactly() -> None:
    """Matches upstream's own `REQUIRED_TOOLS` for the NCR structural build. Not `mafft`/
    `mafft-linsi` — those are routine-tier CDS tools the seed tier has no use for."""
    assert set(tc.SEED_TOOLS) == {"mafft-xinsi", "RNAalifold", "cmbuild", "cmalign"}


def test_the_declaration_covers_seed_on_osx_arm64_only(repository_root: Path) -> None:
    """`seed` is declared `osx-arm64` only in pixi.toml; the declaration must not invent a
    linux-64 entry for an environment the manifest says cannot exist there."""
    declaration = tc.load_declaration(repository_root)
    assert "seed" in declaration["platforms"]["osx-arm64"]
    assert "seed" not in declaration["platforms"].get("linux-64", {})


def test_the_declaration_carries_the_mxscarna_source_pin(repository_root: Path) -> None:
    declaration = tc.load_declaration(repository_root)
    mxscarna = declaration["mxscarna"]
    assert mxscarna["source_url"].startswith("https://mafft.cbrc.jp/")
    assert len(mxscarna["source_sha256"]) == 64


@REQUIRES_SEED_ENV
@REQUIRES_MXSCARNAMOD
def test_the_live_seed_toolchain_matches_the_declaration(
    repository_root: Path, resolved_seed: tc.Toolchain
) -> None:
    tc.assert_declared(repository_root, resolved_seed)


@REQUIRES_SEED_ENV
@REQUIRES_MXSCARNAMOD
def test_mxscarnamod_is_resolved_and_passes_its_liveness_probe(
    resolved_seed: tc.Toolchain,
) -> None:
    assert resolved_seed.mxscarnamod is not None
    assert resolved_seed.mxscarnamod.is_file()


@REQUIRES_SEED_ENV
def test_resolving_the_seed_tier_without_mxscarnamod_fails_with_the_build_command(
    repository_root: Path, tmp_path: Path
) -> None:
    """A missing mxscarnamod must name `scripts/setup_mxscarna.sh`, not fail opaquely."""
    mxscarnamod = repository_root / ".pixi/envs/seed/libexec/mafft/mxscarnamod"
    if not mxscarnamod.exists():
        pytest.skip("mxscarnamod already absent; nothing to hide for this test")
    hidden = tmp_path / "mxscarnamod.hidden"
    mxscarnamod.rename(hidden)
    try:
        with pytest.raises(tc.ToolchainError, match="setup_mxscarna.sh"):
            tc.resolve(
                repository_root, environment=tc.ENV_SEED, tools=tc.SEED_TOOLS, scratch=tmp_path
            )
    finally:
        hidden.rename(mxscarnamod)


@REQUIRES_SEED_ENV
def test_a_broken_mxscarnamod_fails_the_liveness_probe_not_silently(
    repository_root: Path, tmp_path: Path
) -> None:
    """The probe is content-based; confirm it actually rejects a binary that cannot run."""
    real = repository_root / ".pixi/envs/seed/libexec/mafft/mxscarnamod"
    if not real.exists():
        pytest.skip("mxscarnamod not built")
    backup = tmp_path / "mxscarnamod.real"
    real.rename(backup)
    try:
        broken = real
        broken.write_text("#!/bin/sh\nexit 1\n")
        broken.chmod(0o755)
        with pytest.raises(tc.ToolchainError, match="liveness probe"):
            tc.resolve(
                repository_root, environment=tc.ENV_SEED, tools=tc.SEED_TOOLS, scratch=tmp_path
            )
    finally:
        real.unlink(missing_ok=True)
        backup.rename(real)


def test_ci_has_the_toolchain(repository_root: Path) -> None:
    """So the skips above cannot hide the whole file in the one place it must not be skipped."""
    if os.environ.get("CI") != "true":
        pytest.skip("not running in CI")
    assert (repository_root / ".pixi/envs/align/bin/mafft").exists()


# --- mutations: the declaration check, proven to fire -------------------------------------------


@pytest.fixture
def declaration_copy(repository_root: Path, tmp_path: Path) -> Path:
    """A tree with a real lock and a mutable declaration, so mutations touch no tracked file."""
    root = tmp_path / "repo"
    (root / "registry").mkdir(parents=True)
    shutil.copy2(repository_root / tc.PIXI_LOCK, root / tc.PIXI_LOCK)
    shutil.copy2(
        repository_root / tc.TOOLCHAIN_DECLARATION, root / tc.TOOLCHAIN_DECLARATION
    )
    return root


def _mutate(root: Path, mutate) -> None:
    path = root / tc.TOOLCHAIN_DECLARATION
    declaration = json.loads(path.read_text(encoding="utf-8"))
    mutate(declaration)
    path.write_text(json.dumps(declaration, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@REQUIRES_ENV
def test_a_wrong_lock_hash_fails(declaration_copy: Path, resolved: tc.Toolchain) -> None:
    _mutate(declaration_copy, lambda d: d.update(pixi_lock_sha256="0" * 64))
    with pytest.raises(tc.ToolchainError, match="does not match"):
        tc.assert_declared(declaration_copy, resolved)


@REQUIRES_ENV
def test_a_wrong_version_fails(declaration_copy: Path, resolved: tc.Toolchain) -> None:
    def bump(declaration: dict) -> None:
        declaration["platforms"][resolved.platform][tc.ENV_ALIGN]["mafft"]["version"] = "7.500"

    _mutate(declaration_copy, bump)
    with pytest.raises(tc.ToolchainError, match="version is"):
        tc.assert_declared(declaration_copy, resolved)


@REQUIRES_ENV
def test_a_wrong_build_string_fails(declaration_copy: Path, resolved: tc.Toolchain) -> None:
    def repack(declaration: dict) -> None:
        declaration["platforms"][resolved.platform][tc.ENV_ALIGN]["mafft"]["build"] = "hdeadbeef_9"

    _mutate(declaration_copy, repack)
    with pytest.raises(tc.ToolchainError, match="build is"):
        tc.assert_declared(declaration_copy, resolved)


@REQUIRES_ENV
def test_a_missing_package_entry_fails(declaration_copy: Path, resolved: tc.Toolchain) -> None:
    def drop(declaration: dict) -> None:
        del declaration["platforms"][resolved.platform][tc.ENV_ALIGN]["infernal"]

    _mutate(declaration_copy, drop)
    with pytest.raises(tc.ToolchainError, match="does not declare infernal"):
        tc.assert_declared(declaration_copy, resolved)


@REQUIRES_ENV
def test_a_missing_platform_entry_fails(declaration_copy: Path, resolved: tc.Toolchain) -> None:
    def drop(declaration: dict) -> None:
        del declaration["platforms"][resolved.platform]

    _mutate(declaration_copy, drop)
    with pytest.raises(tc.ToolchainError, match="declares nothing for"):
        tc.assert_declared(declaration_copy, resolved)


@REQUIRES_ENV
def test_a_tool_missing_from_the_prefix_is_refused(
    repository_root: Path, tmp_path: Path, scratch: Path
) -> None:
    """A prefix with no binaries must raise with the reconstruction command, not resolve empty."""
    empty = tmp_path / "repo"
    (empty / ".pixi/envs/align/bin").mkdir(parents=True)
    (empty / ".pixi/envs/align/conda-meta").mkdir(parents=True)
    with pytest.raises(tc.ToolchainError, match="is missing from the align environment"):
        tc.resolve(empty, scratch=scratch)


def test_an_absent_prefix_names_the_install_command(tmp_path: Path) -> None:
    with pytest.raises(tc.ToolchainError, match=r"pixi install --locked -e align"):
        tc.resolve(tmp_path, scratch=tmp_path)
