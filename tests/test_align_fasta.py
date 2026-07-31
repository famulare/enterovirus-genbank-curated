"""`align.fasta`: the plain, unwrapped FASTA read/write the scratch-tier tool calls use."""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import fasta
from enterovirus_genbank_curated.contracts import ContractError


def test_write_then_read_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "seqs.fa"
    fasta.write_fasta({"b": "CCGG", "a": "AATT"}, path)
    assert fasta.read_fasta(path) == {"a": "AATT", "b": "CCGG"}


def test_write_sorts_by_id_regardless_of_dict_order(tmp_path: Path) -> None:
    path = tmp_path / "seqs.fa"
    fasta.write_fasta({"zebra": "AAAA", "apple": "CCCC"}, path)
    text = path.read_text()
    assert text.index(">apple") < text.index(">zebra")


def test_write_is_unwrapped_one_line_per_sequence(tmp_path: Path) -> None:
    path = tmp_path / "seqs.fa"
    fasta.write_fasta({"a": "A" * 500}, path)
    lines = path.read_text().splitlines()
    assert lines == [">a", "A" * 500]


def test_read_handles_mafft_style_line_wrapping(tmp_path: Path) -> None:
    path = tmp_path / "wrapped.fa"
    path.write_text(">a\nAAAA\nCCCC\n>b desc ignored\nGGGG\n")
    assert fasta.read_fasta(path) == {"a": "AAAACCCC", "b": "GGGG"}


def test_read_refuses_a_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "dup.fa"
    path.write_text(">a\nAAAA\n>a\nCCCC\n")
    with pytest.raises(ContractError, match="two records"):
        fasta.read_fasta(path)
