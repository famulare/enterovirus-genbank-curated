"""`align.scratch.Scratch`: deterministic run-directory naming off a random root."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import scratch as sc
from enterovirus_genbank_curated.contracts import ContractError


def test_create_makes_a_fresh_directory_under_the_default_temp_tree() -> None:
    scratch = sc.create()
    assert scratch.root.is_dir()
    assert scratch.root.name.startswith(sc.RUN_DIR_PREFIX)


def test_run_dir_name_encodes_index_and_label(tmp_path: Path) -> None:
    scratch = sc.Scratch(root=tmp_path)
    run_dir = scratch.run_dir(7, "mafft_add_backbone")
    assert run_dir.name == "0007-mafft_add_backbone"
    assert run_dir.is_dir()
    assert run_dir.parent == tmp_path


def test_run_dir_names_only_depend_on_index_and_label_not_on_when_theyre_created(
    tmp_path: Path,
) -> None:
    """The property that makes two builds comparable path-for-path once the mkdtemp root is
    stripped: the *name* of a run dir never depends on wall-clock time or call order elsewhere."""
    first_root = tmp_path / "run1"
    second_root = tmp_path / "run2"
    first_root.mkdir()
    second_root.mkdir()
    first = sc.Scratch(root=first_root).run_dir(3, "cds_seed")
    second = sc.Scratch(root=second_root).run_dir(3, "cds_seed")
    assert first.name == second.name


def test_a_label_is_slugged_to_a_safe_path_component(tmp_path: Path) -> None:
    scratch = sc.Scratch(root=tmp_path)
    run_dir = scratch.run_dir(0, "cds/pass 1 (backbone)")
    assert run_dir.parent == tmp_path
    assert "/" not in run_dir.name[5:]  # past the "0000-" index prefix


def test_reusing_the_same_index_twice_is_refused(tmp_path: Path) -> None:
    scratch = sc.Scratch(root=tmp_path)
    scratch.run_dir(0, "first")
    with pytest.raises(ContractError, match="already exists"):
        scratch.run_dir(0, "first")


def test_two_different_labels_at_the_same_index_still_collide(tmp_path: Path) -> None:
    """Slugging could make two distinct labels collide; that must still be refused, not silently
    reuse one directory for two different steps."""
    scratch = sc.Scratch(root=tmp_path)
    scratch.run_dir(0, "a b")
    with pytest.raises(ContractError, match="already exists"):
        scratch.run_dir(0, "a.b")
