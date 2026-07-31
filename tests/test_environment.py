"""`pixi.toml`, `pixi.lock` and `pyproject.toml` must agree about what this build runs.

The alignment layer needs native binaries — mafft and Infernal are not on PyPI — so the environment
moved from uv/pip to pixi, which resolves `[pypi-dependencies]` with uv internally and locks the
result. That keeps `biopython==1.87` and `duckdb==1.5.5` as the same exact wheels rather than
loosening the pins the parity gate rests on, but it also creates a second place those versions are
written down. Two independent declarations of the same fact is this repository's standing pattern;
two declarations that can silently disagree is not. These tests are what makes it the former.

The runtime assertions matter more than the text ones: they check the interpreter and libraries
actually in use, so a lock that resolved differently from what the manifest says fails here rather
than at parity time.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

import pytest

PIXI_MANIFEST = "pixi.toml"
PIXI_LOCK = "pixi.lock"
PYPROJECT = "pyproject.toml"

# The environment the build and CI run in. `seed` exists only to hand native binaries to a child
# process and deliberately does not contain the project.
BUILD_ENVIRONMENT = "align"

# Pinned exactly: GenBank parse output is version-sensitive and the parity gate is byte-exact.
PINNED_RUNTIME = {"biopython": "1.87", "duckdb": "1.5.5"}
PINNED_NATIVE = {"mafft": "7.526", "infernal": "1.1.5"}
PINNED_PYTHON_MINOR = "3.12"


@pytest.fixture(scope="module")
def pixi_manifest(repository_root: Path) -> dict:
    return tomllib.loads((repository_root / PIXI_MANIFEST).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pyproject(repository_root: Path) -> dict:
    return tomllib.loads((repository_root / PYPROJECT).read_text(encoding="utf-8"))


def test_the_two_manifests_agree_on_the_runtime_pins(
    pixi_manifest: dict, pyproject: dict
) -> None:
    """A version bump has to touch both files or fail here."""
    pypi = pixi_manifest["feature"][BUILD_ENVIRONMENT]["pypi-dependencies"]
    declared = {
        name.lower(): spec.removeprefix("==")
        for name, spec in pypi.items()
        if isinstance(spec, str)
    }
    for name, version in PINNED_RUNTIME.items():
        assert declared[name] == version, f"{PIXI_MANIFEST} moved {name} off {version}"

    for entry in pyproject["project"]["dependencies"]:
        name, _, version = entry.partition("==")
        assert PINNED_RUNTIME[name.strip().lower()] == version.strip(), (
            f"{PYPROJECT} and {PIXI_MANIFEST} disagree about {name}"
        )


def test_the_installed_libraries_match_the_pins() -> None:
    """The check that actually bites: what is imported, not what is written down."""
    import Bio
    import duckdb

    assert Bio.__version__ == PINNED_RUNTIME["biopython"]
    assert duckdb.__version__ == PINNED_RUNTIME["duckdb"]


def test_the_interpreter_is_the_pinned_minor_version() -> None:
    """3.12, not 3.13.

    `viennarna` is a py313 build, so a single-environment pixi setup would have dragged the project
    interpreter to 3.13 and re-resolved biopython against a version the parity gate has never run
    on. The two-environment split exists to prevent exactly that, and this asserts it held.
    """
    assert f"{sys.version_info.major}.{sys.version_info.minor}" == PINNED_PYTHON_MINOR


def test_requires_python_still_admits_the_pinned_interpreter(pyproject: dict) -> None:
    assert pyproject["project"]["requires-python"] == ">=3.12,<3.14"


def test_the_native_tools_are_pinned_exactly(pixi_manifest: dict) -> None:
    """`*` would let `pixi update` move an aligner with an empty manifest diff."""
    deps = pixi_manifest["feature"][BUILD_ENVIRONMENT]["dependencies"]
    for name, version in PINNED_NATIVE.items():
        assert deps[name] == f"=={version}", f"{name} is not pinned exactly"
    assert deps["python"] == f"{PINNED_PYTHON_MINOR}.*"


def test_the_lock_resolves_the_pinned_versions_on_both_platforms(repository_root: Path) -> None:
    """CI runs linux-64 and the author runs osx-arm64; both must get the same tool versions."""
    lock = (repository_root / PIXI_LOCK).read_text(encoding="utf-8")
    align = re.search(r"^  align:\n(.*?)(?=^  \w[\w-]*:\n|^packages:)", lock, re.S | re.M)
    assert align, "pixi.lock has no align environment"
    block = align.group(1)
    for platform in ("linux-64", "osx-arm64"):
        assert f"      {platform}:" in block, f"align does not cover {platform}"
    for name, version in PINNED_NATIVE.items():
        assert f"/{name}-{version}-" in block, f"align lock is missing {name} {version}"
    assert f"/python-{PINNED_PYTHON_MINOR}." in block
    # The interpreter that must NOT be here. See test_the_interpreter_is_the_pinned_minor_version.
    assert "/python-3.13." not in block, "python 3.13 leaked into the build environment"


def test_the_seed_environment_is_isolated_and_single_platform(
    pixi_manifest: dict, repository_root: Path
) -> None:
    """`seed` may carry python 3.13, but must not carry the project nor share its solve."""
    assert pixi_manifest["feature"]["seed"]["platforms"] == ["osx-arm64"]
    assert "pypi-dependencies" not in pixi_manifest["feature"]["seed"]
    environments = pixi_manifest["environments"]
    assert environments["align"].get("solve-group") != environments["seed"].get("solve-group") or (
        environments["seed"].get("solve-group") is None
    )


def test_no_second_python_install_path_survives(repository_root: Path) -> None:
    """`requirements-dev.txt` was retired into the manifest; its return would split the truth."""
    assert not (repository_root / "requirements-dev.txt").exists(), (
        "requirements-dev.txt is back. Dev dependencies belong in pixi.toml's "
        "[feature.align.pypi-dependencies]; two install paths is the problem this replaced."
    )


def test_no_workflow_or_script_puts_the_pixi_prefix_on_path(repository_root: Path) -> None:
    """PATH prefixing belongs in the env dict handed to a child, never in this repo's own PATH.

    Upstream activated its toolchain with `export PATH=".../envs/default/bin:$PATH"` in eight script
    docstrings. Doing that here would put a conda `python` and `perl` ahead of the interpreter
    running the build. The alignment runner passes PATH to the child explicitly instead, which is
    also what keeps `mafft-xinsi`'s bare-name sibling resolution working.
    """
    pattern = re.compile(r"(export\s+PATH|PATH\s*=)[^\n]*\.pixi/envs")
    roots = [repository_root / ".github", repository_root / "scripts", repository_root / "docs"]
    offenders = []
    for root in roots:
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".yml", ".yaml", ".sh", ".md", ".py"}:
                continue
            if pattern.search(path.read_text(encoding="utf-8", errors="replace")):
                offenders.append(str(path.relative_to(repository_root)))
    assert not offenders, f"these put the pixi prefix on PATH: {offenders}"


def test_ci_installs_the_locked_environment(repository_root: Path) -> None:
    """`locked: true` is what makes the manifest pins reviewable rather than decorative."""
    workflow = (repository_root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "prefix-dev/setup-pixi" in workflow
    assert "locked: true" in workflow
    assert "pip install" not in workflow, "the second install path is back in CI"
