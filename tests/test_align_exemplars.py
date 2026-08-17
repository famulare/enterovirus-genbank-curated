"""`align.exemplars`: the seed-only clade exemplars, and the column bookkeeping that removes them.

The committed files are inputs-of-record with no producer in this repository, so these tests are
mostly about the checks that stand between a truncated or swapped file and a silently worse
alignment. `tests/test_alignment_seeds.py` covers the hash pinning; this covers the content.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import codon, exemplars
from enterovirus_genbank_curated.align.segment import translate
from enterovirus_genbank_curated.contracts import ContractError

TABLE_HEADER = (
    "exemplar_id\tanchors_family\torganism\tdefinition\tgenome_nt\tcds_start_1based\t"
    "cds_end_1based_inclusive\torf_nt\torf_aa\tambiguous_nt"
)


def write_pair(root: Path, fasta: str, table: str) -> Path:
    seed_dir = root / "registry" / "alignment_seeds"
    seed_dir.mkdir(parents=True, exist_ok=True)
    (seed_dir / exemplars.EXEMPLAR_FASTA).write_text(fasta, encoding="utf-8")
    (seed_dir / exemplars.EXEMPLAR_TABLE).write_text(table, encoding="utf-8")
    return root


def one_pair(root: Path, orf_nt: str, *, declared_nt: int | None = None,
             declared_aa: int | None = None) -> Path:
    aa = translate(orf_nt)
    row = "\t".join([
        "NC_TEST.1", "RV-A", "Rhinovirus A", "test exemplar", str(len(orf_nt) + 100), "101",
        str(100 + len(orf_nt)), str(declared_nt if declared_nt is not None else len(orf_nt)),
        str(declared_aa if declared_aa is not None else len(aa)), "0",
    ])
    return write_pair(root, f">NC_TEST.1\n{orf_nt}\n", f"{TABLE_HEADER}\n{row}\n")


# --- the real committed files ---------------------------------------------------------------------


def test_the_committed_exemplars_load_and_anchor_both_rhinovirus_species(
    repository_root: Path,
) -> None:
    loaded = exemplars.load_clade_exemplars(repository_root)
    assert len(loaded) == 4
    assert {e.anchors_family for e in loaded} == {"RV-A", "RV-B"}
    # Two per species, matching CodonSpec.seed_per_type -- the selection rule, not a coincidence.
    assert sorted(e.anchors_family for e in loaded) == ["RV-A", "RV-A", "RV-B", "RV-B"]
    for exemplar in loaded:
        assert 2_100 < len(exemplar.aa) < 2_250, "an enterovirus polyprotein, not a fragment"
        assert len(exemplar.orf_nt) == 3 * len(exemplar.aa)
        assert "*" not in exemplar.aa
        assert exemplar.row_name.startswith(exemplars.EXEMPLAR_PREFIX)


def test_no_committed_exemplar_id_could_be_mistaken_for_a_row(repository_root: Path) -> None:
    """The row name is what protects a real record from being overwritten by an exemplar, so it has
    to be unreachable as an accession rather than merely unlikely."""
    loaded = exemplars.load_clade_exemplars(repository_root)
    assert all(not exemplars.is_exemplar_row(e.exemplar_id) for e in loaded)
    assert all(exemplars.is_exemplar_row(e.row_name) for e in loaded)


# --- the content checks ---------------------------------------------------------------------------


def test_a_truncated_fasta_is_caught_by_the_declared_length(tmp_path: Path) -> None:
    orf = "ATG" + "GCC" * 20
    root = one_pair(tmp_path, orf, declared_nt=len(orf) + 3)
    with pytest.raises(ContractError, match="declares orf_nt"):
        exemplars.load_clade_exemplars(root)


def test_a_declared_aa_length_that_disagrees_is_caught(tmp_path: Path) -> None:
    orf = "ATG" + "GCC" * 20
    root = one_pair(tmp_path, orf, declared_aa=999)
    with pytest.raises(ContractError, match="declares orf_aa"):
        exemplars.load_clade_exemplars(root)


def test_a_partial_codon_is_caught(tmp_path: Path) -> None:
    root = one_pair(tmp_path, "ATGGC")
    with pytest.raises(ContractError, match="whole number of codons"):
        exemplars.load_clade_exemplars(root)


def test_an_internal_stop_is_caught(tmp_path: Path) -> None:
    """A polyprotein with a stop in it is not a polyprotein, and an exemplar that carries one would
    put an `X` into the seed at a position every fragment in the clade aligns against."""
    root = one_pair(tmp_path, "ATG" + "GCC" * 5 + "TAA" + "GCC" * 5)
    with pytest.raises(ContractError, match="stop codon"):
        exemplars.load_clade_exemplars(root)


def test_the_table_and_the_fasta_must_name_the_same_records(tmp_path: Path) -> None:
    root = write_pair(
        tmp_path,
        ">NC_TEST.1\nATGGCCGCC\n>NC_EXTRA.1\nATGGCCGCC\n",
        f"{TABLE_HEADER}\nNC_TEST.1\tRV-A\tx\tx\t100\t1\t9\t9\t3\t0\n",
    )
    with pytest.raises(ContractError, match="present but undeclared"):
        exemplars.load_clade_exemplars(root)


def test_an_exemplar_that_is_also_a_carve_record_is_refused(repository_root: Path) -> None:
    loaded = exemplars.load_clade_exemplars(repository_root)
    exemplars.assert_disjoint_from(loaded, frozenset({"AY184219", "AF499635"}))
    with pytest.raises(ContractError, match="are also carve records"):
        exemplars.assert_disjoint_from(loaded, frozenset({"NC_001617.1"}))


def test_a_population_accession_wearing_the_exemplar_prefix_is_refused(
    repository_root: Path,
) -> None:
    loaded = exemplars.load_clade_exemplars(repository_root)
    with pytest.raises(ContractError, match="collide with a seed exemplar row"):
        exemplars.assert_disjoint_from(
            loaded, frozenset({f"{exemplars.EXEMPLAR_PREFIX}SOMETHING"})
        )


# --- drop_exemplar_only_columns -------------------------------------------------------------------


def test_columns_only_an_exemplar_occupied_go_with_it() -> None:
    """Column 2 exists solely because the exemplar has a residue there. Removing the exemplar
    without removing the column would leave the shipped width paying for a sequence that is not in
    the release -- and an all-gap column that `drop_unsequenced_codon_columns` deliberately will not
    touch, because to that function an unoccupied column is not an unsequenced one."""
    aa_aln = {
        "A": "MA-KL",
        "B": "MA-KL",
        f"{exemplars.EXEMPLAR_PREFIX}X": "MAWKL",
    }
    kept, dropped = codon.drop_exemplar_only_columns(
        aa_aln, frozenset({f"{exemplars.EXEMPLAR_PREFIX}X"})
    )
    assert dropped == 1
    assert kept == {"A": "MAKL", "B": "MAKL"}


def test_a_column_a_real_record_shares_with_an_exemplar_stays() -> None:
    aa_aln = {"A": "MAWKL", f"{exemplars.EXEMPLAR_PREFIX}X": "MAWKL"}
    kept, dropped = codon.drop_exemplar_only_columns(
        aa_aln, frozenset({f"{exemplars.EXEMPLAR_PREFIX}X"})
    )
    assert dropped == 0
    assert kept == {"A": "MAWKL"}


def test_an_alignment_of_nothing_but_exemplars_is_refused() -> None:
    with pytest.raises(ContractError, match="contributed nothing"):
        codon.drop_exemplar_only_columns(
            {f"{exemplars.EXEMPLAR_PREFIX}X": "MAWKL"},
            frozenset({f"{exemplars.EXEMPLAR_PREFIX}X"}),
        )


def test_the_committed_fasta_is_plain_wrapped_nucleotide(repository_root: Path) -> None:
    """Guards the file's shape rather than its content. A protein FASTA dropped in here would fail
    the length check only by luck -- 2,164 residues is not 6,492 nt -- so the alphabet is checked
    directly, over the sequence lines alone."""
    text = (repository_root / "registry" / "alignment_seeds" / exemplars.EXEMPLAR_FASTA).read_text()
    lines = text.splitlines()
    headers = [line for line in lines if line.startswith(">")]
    residues = "".join(line for line in lines if not line.startswith(">"))
    assert len(headers) == 4
    assert set(residues) <= set("ACGTNRYWSKMBDHV"), "not nucleotide"
    assert set(residues) >= set("ACGT")
    assert len(residues) % 3 == 0
