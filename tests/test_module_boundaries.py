"""The build half of the package may not reach the shipped release.

`sandbox.READ_REFUSED_DIRS` is the guarantee that actually holds at runtime; this file is the cheap
check that catches the ordinary mistake at review time instead of in a guarded corpus run.

The scan is done in Python over `Path.rglob` rather than by shelling out to `grep`, because the
review that produced `docs/review-backlog.md` found the author's `grep` alias silently skipping
`.gitignore`d files (root cause R1) and invalidating every reachability claim made with it.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = "src/enterovirus_genbank_curated"

# Subpackages and modules that participate in a build. None of them may name `final/` or import the
# oracle. `contracts.py` is included: `build.py` imports it, so a release read there would be
# reachable from every build.
#
# Every entry must exist — `rglob` over a missing directory returns nothing, so listing a tree that
# has not been created yet (or misspelling one) would silently cover zero files while looking like
BUILD_TREES = ("curate", "derive", "export", "genbank", "registry", "validation")
BUILD_MODULES = ("build.py", "contracts.py", "sandbox.py")

ORACLE_PACKAGE = "enterovirus_genbank_curated.oracle"

# The single legitimate occurrence: `contracts.validate_parity_spec` checks that every declared
# parity-artifact path carries the release prefix. That is a string being validated, not a path
# being opened. Exempting the one assignment keeps the rule sharp rather than the whole module.
RELEASE_PREFIX_EXEMPTION = 'RELEASE_PATH_PREFIX = "final/"'

# `align/` is not a build tree: its charter is to derive alignment inputs from the shipped release
# because the pipeline stages that would produce them natively (`derive`, `curate`, and an eventual
# alignment-specific stage) do not exist yet — the same justification `oracle/` has for reading
# `final/`, aimed at derivation rather than comparison. So `align/` is free to import the oracle and
# free to read `final/` in general.
#
# `align/contract.py` specifically is not, by decision (2026-07-30): every `final/` path the
# alignment layer needs is declared once in `oracle.parity` and imported from there, so a canonical
# metadata path bug is one constant to fix rather than two definitions that can drift. This is
# narrower than the build-tree rule above — it names one file, not a tree — because only
# `contract.py` claims to be the single declaration point; `align/regions.py` legitimately names its
# own *output* path (the file it regenerates), which is a destination being written, not a shipped
# path being redeclared.
ALIGN_CONTRACT_PATH = "src/enterovirus_genbank_curated/align/contract.py"


def _build_sources(repository_root: Path) -> list[Path]:
    root = repository_root / PACKAGE
    absent_trees = [tree for tree in BUILD_TREES if not (root / tree).is_dir()]
    assert not absent_trees, (
        f"BUILD_TREES names packages that do not exist, so they cover nothing: {absent_trees}"
    )
    found = [
        path
        for tree in BUILD_TREES
        for path in sorted((root / tree).rglob("*.py"))
        if "__pycache__" not in path.parts
    ]
    found += [root / name for name in BUILD_MODULES]
    missing = [p for p in found if not p.is_file()]
    assert not missing, f"declared build modules are absent: {missing}"
    return found


def test_no_build_module_names_the_shipped_release(repository_root: Path) -> None:
    offenders = {
        path.relative_to(repository_root).as_posix(): [
            number
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
            if ('"final/' in line or "'final/" in line)
            and RELEASE_PREFIX_EXEMPTION not in line
        ]
        for path in _build_sources(repository_root)
    }
    named = {path: lines for path, lines in offenders.items() if lines}
    assert not named, f"build modules must not name a final/ path: {named}"


def test_the_release_prefix_exemption_still_describes_real_code(repository_root: Path) -> None:
    """An exemption for a line that no longer exists silently widens the rule above."""
    contracts = (repository_root / PACKAGE / "contracts.py").read_text(encoding="utf-8")
    assert RELEASE_PREFIX_EXEMPTION in contracts


def test_no_build_module_imports_the_oracle(repository_root: Path) -> None:
    offenders: dict[str, list[str]] = {}
    for path in _build_sources(repository_root):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(ORACLE_PACKAGE):
                hits.append(node.module or "")
            elif isinstance(node, ast.Import):
                hits += [a.name for a in node.names if a.name.startswith(ORACLE_PACKAGE)]
        if hits:
            offenders[path.relative_to(repository_root).as_posix()] = hits
    assert not offenders, f"build modules must not import the oracle: {offenders}"


@pytest.mark.parametrize("tree", BUILD_TREES)
def test_no_build_tree_names_the_frozen_legacy_registries(repository_root: Path, tree: str) -> None:
    """`registry/legacy/` is provenance, not input — the same rule as `final/`, different reason."""
    root = repository_root / PACKAGE / tree
    named = [
        path.relative_to(repository_root).as_posix()
        for path in sorted(root.rglob("*.py"))
        if "__pycache__" not in path.parts and "registry/legacy" in path.read_text(encoding="utf-8")
    ]
    assert not named, f"build modules must not name registry/legacy: {named}"


def test_align_contract_names_no_final_path_itself(repository_root: Path) -> None:
    """`align/contract.py` must import every `final/` path from `oracle.parity`, never spell one.

    Same substring mechanism as `test_no_build_module_names_the_shipped_release`: an actual string
    literal reads `"final/` or `'final/`; a docstring mention in backticks does not, which is why
    the module's own extensive prose about *why* it reads `final/` does not trip this.
    """
    path = repository_root / ALIGN_CONTRACT_PATH
    offenders = [
        number
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if '"final/' in line or "'final/" in line
    ]
    assert not offenders, (
        f"{ALIGN_CONTRACT_PATH} names a final/ path directly at line(s) {offenders}; import it "
        f"from oracle.parity instead"
    )


def test_align_contract_imports_its_final_paths_from_oracle(repository_root: Path) -> None:
    """The positive half: every `final/`-backed constant must actually come from `oracle.parity`.

    Guards against satisfying the test above by moving the literal into a different align/ module
    and importing it from there instead of from oracle — which would keep the letter of the rule
    while defeating its point.
    """
    path = repository_root / ALIGN_CONTRACT_PATH
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    oracle_parity_module = "enterovirus_genbank_curated.oracle.parity"
    oracle_parity_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == oracle_parity_module:
            oracle_parity_names |= {alias.name for alias in node.names}
    expected = {
        "SHIPPED_CANONICAL_METADATA",
        "SHIPPED_CANONICAL_FASTA",
        "SHIPPED_SEQUENCE_EVIDENCE",
        "SHIPPED_SOURCE_FEATURES",
        "SHIPPED_SOURCE_FEATURE_PARTS",
        "SHIPPED_SOURCE_FEATURE_QUALIFIERS",
    }
    missing = expected - oracle_parity_names
    assert not missing, (
        f"{ALIGN_CONTRACT_PATH} no longer imports {sorted(missing)} from oracle.parity"
    )
