"""`align.anchored`: the pairwise Sabin anchor, the TAB engine, and the reference-frame projection.

Aligner-free throughout — this stack is pure Biopython, which is the reason it can be reviewed and
tested on a machine with no MAFFT or Infernal installed. The real-data tests read `final/` and are
kept to small slices so the file stays fast; the whole-population run belongs to the build verbs.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import anchored, contract
from enterovirus_genbank_curated.align import population as population_module
from enterovirus_genbank_curated.contracts import ContractError

# --- aligner configuration ----------------------------------------------------------------------


def test_nucleotide_aligner_is_semi_global_with_free_end_gaps() -> None:
    """Free ends, expensive interior: a fragment pays nothing to sit inside the genome but cannot
    shred itself to buy mismatches. Both halves matter, so both are pinned."""
    aligner = anchored.nucleotide_aligner()
    assert aligner.mode == "global"
    assert aligner.match_score == 2.0
    assert aligner.mismatch_score == -1.0
    assert aligner.open_internal_gap_score == -50.0
    assert aligner.extend_internal_gap_score == -10.0
    for score in (
        aligner.open_left_gap_score, aligner.extend_left_gap_score,
        aligner.open_right_gap_score, aligner.extend_right_gap_score,
    ):
        assert score == 0.0


def test_protein_aligner_uses_blosum62_with_free_end_gaps() -> None:
    aligner = anchored.protein_aligner()
    assert aligner.mode == "global"
    assert aligner.open_internal_gap_score == -11.0
    assert aligner.extend_internal_gap_score == -1.0
    assert aligner.open_left_gap_score == 0.0
    assert aligner.open_right_gap_score == 0.0
    assert aligner.substitution_matrix is not None


# --- translation --------------------------------------------------------------------------------


def test_translate_from_respects_the_offset_and_drops_a_partial_codon() -> None:
    assert anchored.translate_from("ATGGCC", 0) == "MA"
    assert anchored.translate_from("NATGGCC", 1) == "MA"
    # 7 nt from offset 0 is two whole codons plus one leftover base, which is dropped.
    assert anchored.translate_from("ATGGCCA", 0) == "MA"


def test_translate_from_maps_an_ambiguous_codon_to_x() -> None:
    assert anchored.translate_from("ATGNNN", 0) == "MX"


def test_has_internal_stop_ignores_a_terminal_stop() -> None:
    assert not anchored.has_internal_stop("MA*")
    assert not anchored.has_internal_stop("MA")
    assert anchored.has_internal_stop("M*A")


# --- orientation --------------------------------------------------------------------------------


def test_best_alignment_picks_the_reverse_complement_when_it_scores_higher() -> None:
    reference = "ATGGCCTTTAAAGGGCCCTTTACG"
    # The query is the reference's reverse complement, so reading it forward matches nothing.
    query = "CGTAAAGGGCCCTTTAAAGGCCAT"
    strand, _alignment, oriented = anchored.best_alignment(
        anchored.nucleotide_aligner(), reference, query
    )
    assert strand == anchored.REVERSE_COMPLEMENT
    assert oriented == reference


def test_best_alignment_keeps_forward_when_the_query_is_already_oriented() -> None:
    reference = "ATGGCCTTTAAAGGGCCCTTTACG"
    strand, _alignment, oriented = anchored.best_alignment(
        anchored.nucleotide_aligner(), reference, reference
    )
    assert strand == anchored.FORWARD
    assert oriented == reference


# --- oriented_coding_start ----------------------------------------------------------------------


def test_oriented_coding_start_forward_plus_applies_codon_start() -> None:
    cds = {"start": 10, "end": 100, "strand": "+", "codon_start": 1}
    assert anchored.oriented_coding_start(cds, anchored.FORWARD, 200) == 9
    assert anchored.oriented_coding_start({**cds, "codon_start": 3}, anchored.FORWARD, 200) == 11


def test_oriented_coding_start_reverse_minus_measures_from_the_far_end() -> None:
    cds = {"start": 10, "end": 100, "strand": "-", "codon_start": 1}
    # A deposited 1-based position p sits at oriented index (length - p).
    assert anchored.oriented_coding_start(cds, anchored.REVERSE_COMPLEMENT, 200) == 100
    assert (
        anchored.oriented_coding_start(
            {**cds, "codon_start": 2}, anchored.REVERSE_COMPLEMENT, 200
        )
        == 101
    )


@pytest.mark.parametrize(
    ("strand", "cds_strand"),
    [(anchored.FORWARD, "-"), (anchored.REVERSE_COMPLEMENT, "+")],
)
def test_oriented_coding_start_refuses_a_strand_disagreement(strand: str, cds_strand: str) -> None:
    """Only (forward, +) and (reverse_complement, -) are self-consistent. Anything else means the
    annotation and the anchor disagree, and the caller must infer the frame instead of guessing."""
    cds = {"start": 10, "end": 100, "strand": cds_strand, "codon_start": 1}
    assert anchored.oriented_coding_start(cds, strand, 200) is None


# --- codon_blocks_from_aa -----------------------------------------------------------------------


class _FakeAaAlignment:
    """Two aligned protein rows — all `codon_blocks_from_aa` indexes is [0] and [1]."""

    def __init__(self, reference_row: str, query_row: str) -> None:
        self._rows = (reference_row, query_row)

    def __getitem__(self, index: int) -> str:
        return self._rows[index]


def test_codon_blocks_from_aa_turns_each_ungapped_run_into_one_nt_block() -> None:
    ref_blocks, query_blocks = anchored.codon_blocks_from_aa(
        _FakeAaAlignment("MAK", "MAK"), ref_codon0=0, query_codon0=0
    )
    assert ref_blocks == [(0, 9)]
    assert query_blocks == [(0, 9)]


def test_codon_blocks_from_aa_splits_on_a_query_gap_and_advances_only_the_reference() -> None:
    """A deletion: the reference keeps consuming codons across the gap, the query does not."""
    ref_blocks, query_blocks = anchored.codon_blocks_from_aa(
        _FakeAaAlignment("MAK", "M-K"), ref_codon0=0, query_codon0=0
    )
    assert ref_blocks == [(0, 3), (6, 9)]
    assert query_blocks == [(0, 3), (3, 6)]


def test_codon_blocks_from_aa_splits_on_a_reference_gap_for_an_insertion() -> None:
    ref_blocks, query_blocks = anchored.codon_blocks_from_aa(
        _FakeAaAlignment("M-K", "MAK"), ref_codon0=0, query_codon0=0
    )
    assert ref_blocks == [(0, 3), (3, 6)]
    assert query_blocks == [(0, 3), (6, 9)]


def test_codon_blocks_from_aa_honours_the_starting_offsets() -> None:
    ref_blocks, query_blocks = anchored.codon_blocks_from_aa(
        _FakeAaAlignment("MA", "MA"), ref_codon0=743, query_codon0=12
    )
    assert ref_blocks == [(743, 749)]
    assert query_blocks == [(12, 18)]


# --- project ------------------------------------------------------------------------------------


def _block(
    ref_blocks, query_blocks, method: str = anchored.METHOD_CODON
) -> anchored.BlockAlignment:
    return anchored.BlockAlignment(
        ref_blocks=tuple(ref_blocks), query_blocks=tuple(query_blocks),
        method=method, internal_stop=False, recovered=None,
    )


def test_project_writes_covered_reference_positions_and_gaps_the_rest() -> None:
    # Query covers reference [2, 5) only; the flanks are unsequenced, so they are gaps.
    row = anchored.project(_block([(2, 5)], [(0, 3)]), "GGG", cds_start0=0, cds_end0=8)
    assert row == "--GGG---"


def test_project_gaps_a_deletion_relative_to_the_reference() -> None:
    """Two reference blocks with no reference position between them for the query to occupy."""
    row = anchored.project(_block([(0, 2), (4, 6)], [(0, 2), (2, 4)]), "AACC", 0, 6)
    assert row == "AA--CC"


def test_project_drops_an_insertion_relative_to_the_reference() -> None:
    """The two query bases at oriented [2, 4) have no reference position, so they vanish — the
    documented lossiness of a fixed reference frame, and the reason the unified stack exists."""
    row = anchored.project(_block([(0, 2), (2, 4)], [(0, 2), (4, 6)]), "AAGGCC", 0, 4)
    assert row == "AACC"
    assert "G" not in row


def test_project_width_is_fixed_by_the_reference_span_not_the_query() -> None:
    row = anchored.project(_block([(10, 13)], [(0, 3)]), "AAA", cds_start0=10, cds_end0=100)
    assert len(row) == 90
    assert row.startswith("AAA")


def test_project_ignores_blocks_outside_the_cds_span() -> None:
    """A block wholly in the 5'UTR must not bleed into a CDS-span projection."""
    row = anchored.project(_block([(0, 3)], [(0, 3)]), "AAA", cds_start0=10, cds_end0=13)
    assert row == "---"


def test_project_of_an_empty_block_set_is_all_gap() -> None:
    row = anchored.project(_block([], []), "AAA", cds_start0=0, cds_end0=5)
    assert row == "-----"


# --- the codon-phase audit ----------------------------------------------------------------------


def test_gap_audit_counts_a_non_multiple_of_three_deletion() -> None:
    # Covered span is the whole width; one 2 nt gap inside it.
    row = "AAA--AAA"
    alignment = _block([(0, 3), (5, 8)], [(0, 3), (3, 6)])
    non_multiple, misphased = anchored._gap_audit(row, alignment, 0, 8)
    assert non_multiple == 1
    assert misphased == 0


def test_gap_audit_accepts_an_in_phase_multiple_of_three_deletion() -> None:
    row = "AAA---AAA"
    alignment = _block([(0, 3), (6, 9)], [(0, 3), (3, 6)])
    assert anchored._gap_audit(row, alignment, 0, 9) == (0, 0)


def test_gap_audit_flags_a_misphased_multiple_of_three_deletion() -> None:
    """A ×3 gap that does not start on a codon boundary is a codon-smeared deletion: the right
    length, the wrong place."""
    row = "AAAA---AA"
    alignment = _block([(0, 4), (7, 9)], [(0, 4), (4, 6)])
    non_multiple, misphased = anchored._gap_audit(row, alignment, 0, 9)
    assert non_multiple == 0
    assert misphased == 1


def test_gap_audit_ignores_uncovered_flanks_of_a_partial_record() -> None:
    """The decisive case: a fragment's unsequenced flanks are not deletions. Counting them would
    make every partial record look frameshifted."""
    row = "----AAA--"  # leading 4 and trailing 2 gaps are outside the covered span
    alignment = _block([(4, 7)], [(0, 3)])
    assert anchored._gap_audit(row, alignment, 0, 9) == (0, 0)


# --- the do-no-harm guards ----------------------------------------------------------------------

_REF = "ATG" + "AAAGAAGATCTGTCTGTTATTCCACGTACC" * 3 + "TAA"


def _align(query: str, *, pdist_pp: float, aa_pp: float = 30.0, bypass: bool = False):
    return anchored.codon_aware_align(
        anchored.nucleotide_aligner(), _REF, (1, len(_REF)), query, None,
        pdist_guard_increase_pp=pdist_pp, aa_guard_increase_pp=aa_pp, guard_bypass=bypass,
    )


def test_nucleotide_guard_threshold_is_actually_consulted() -> None:
    """A guard nothing can satisfy must force the nucleotide anchor; a guard nothing can trip must
    not. This is the plumbing test: an earlier draft read both thresholds off the dataclass's class
    attributes, so a per-artifact override would have been silently ignored."""
    query = _REF[:60]
    _, permissive, _ = _align(query, pdist_pp=1e9)
    _, impossible, _ = _align(query, pdist_pp=-1e9)
    assert permissive.method != anchored.METHOD_NT_BETTER
    assert impossible.method == anchored.METHOD_NT_BETTER


def test_guard_bypass_overrides_an_impossible_nucleotide_guard() -> None:
    query = _REF[:60]
    _, guarded, _ = _align(query, pdist_pp=-1e9)
    _, bypassed, _ = _align(query, pdist_pp=-1e9, bypass=True)
    assert guarded.method == anchored.METHOD_NT_BETTER
    assert bypassed.method != anchored.METHOD_NT_BETTER


def test_a_query_that_never_reaches_the_cds_falls_back_to_nucleotide() -> None:
    """The reference CDS is declared as the last few bases only, so a query matching the front of
    the reference cannot touch it."""
    _, alignment, _ = anchored.codon_aware_align(
        anchored.nucleotide_aligner(), _REF, (len(_REF) - 2, len(_REF)), _REF[:30], None,
        pdist_guard_increase_pp=2.0, aa_guard_increase_pp=30.0,
    )
    assert alignment.method == anchored.METHOD_NT_FALLBACK
    assert alignment.ref_blocks == ()


# --- build_anchored_cds_block: real data, small slices ------------------------------------------


@pytest.fixture(scope="module")
def pv1(repository_root: Path) -> population_module.AlignmentPopulation:
    return population_module.load_population(repository_root, "PV1_unified")


def _slice(pop: population_module.AlignmentPopulation, accessions: list[str]):
    wanted = set(accessions)
    return replace(pop, records=tuple(r for r in pop.records if r.accession in wanted))


def test_the_sabin_reference_row_recovers_its_own_cds_exactly(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    """Acceptance assertion 9 over the CDS span: the reference projected onto its own frame must be
    the reference. If this drifts, every column number in the artifact is wrong."""
    block = anchored.build_anchored_cds_block(_slice(pv1, ["AY184219"]), repository_root)
    assert block.cds_start == 743
    assert block.cds_end == 7372
    assert block.width_nt == 6630
    assert block.width_nt % 3 == 0
    assert block.aligned_nt["AY184219"] == block.reference_row
    assert block.reference_row.startswith("ATG")


def test_a_five_prime_utr_only_fragment_is_absent_from_the_cds_block(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    """`A37539` is 628 nt and aligns to reference 1..628, wholly inside the 5'UTR (CDS starts 743).
    It has no CDS residues at all, so it is *absent* from `aligned_nt` rather than present as an
    all-gap row — otherwise the coverage sidecar could not distinguish "no data here" from "covered
    and entirely deleted". It still appears in `rows`, so the audit trail is complete, and
    `align.stitch` pads its stitched row identically either way."""
    block = anchored.build_anchored_cds_block(
        _slice(pv1, ["A37539", "AY184219"]), repository_root
    )
    assert "A37539" not in block.aligned_nt
    audited = {row.accession: row for row in block.rows}
    assert set(audited["A37539"].cds_row) == {"-"}
    assert len(audited["A37539"].cds_row) == block.width_nt


def test_every_row_is_the_declared_fixed_width(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    accessions = [r.accession for r in pv1.records[:12]] + ["AY184219"]
    block = anchored.build_anchored_cds_block(_slice(pv1, accessions), repository_root)
    # Every record is audited; only those with CDS residues are published as rows.
    assert {row.accession for row in block.rows} == set(accessions)
    assert set(block.aligned_nt) <= set(accessions)
    for row in block.aligned_nt.values():
        assert len(row) == block.width_nt
        assert row.count("-") < len(row)
    for audited in block.rows:
        assert len(audited.cds_row) == block.width_nt


def test_build_refuses_a_population_with_no_anchor_spec(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    unanchored = replace(pv1, spec=replace(pv1.spec, anchor=None))
    with pytest.raises(ContractError, match="no declared AnchorSpec"):
        anchored.build_anchored_cds_block(unanchored, repository_root)


def test_build_refuses_when_the_reference_is_not_a_population_member(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    """The reference row must come from the population itself, not be imported alongside it —
    otherwise the artifact carries a row that metadata does not account for."""
    without_reference = _slice(pv1, [r.accession for r in pv1.records[:4]])
    without_reference = replace(
        without_reference,
        records=tuple(r for r in without_reference.records if r.accession != "AY184219"),
    )
    with pytest.raises(ContractError, match="is not in the .* population"):
        anchored.build_anchored_cds_block(without_reference, repository_root)


def test_the_anchor_spec_reference_must_match_the_derived_regions(
    repository_root: Path, pv1: population_module.AlignmentPopulation
) -> None:
    """Two independent statements of which accession frames PV1 — `AnchorSpec` and the regions
    derived from the source features. A disagreement means one of them is stale."""
    wrong = replace(
        pv1, spec=replace(pv1.spec, anchor=replace(pv1.spec.anchor, reference_accession="AY184220"))
    )
    with pytest.raises(ContractError, match="derived regions name reference"):
        anchored.build_anchored_cds_block(_slice(wrong, ["AY184219"]), repository_root)


# --- the declared contract ----------------------------------------------------------------------


def test_every_anchored_artifact_declares_a_reference_and_a_per_serotype_cm() -> None:
    for name, spec in contract.ARTIFACTS.items():
        if spec.stack != "anchored":
            continue
        assert spec.anchor is not None, name
        assert spec.ncr is not None, name
        assert spec.anchor.reference_accession == contract.SABIN_REFERENCE[spec.anchor.serotype]
        serotype = spec.anchor.serotype.lower()
        assert spec.ncr.five_prime.cm_path.endswith(f"{serotype}_ncr_5p.cm")
        assert spec.ncr.three_prime.cm_path.endswith(f"{serotype}_ncr_3p.cm")


def test_the_hand_adjudicated_guard_bypass_is_declared_and_narrow() -> None:
    """`OR538733` is the one record whose nucleotide guard was manually overruled. Three sibling
    accessions were evaluated and rejected, so the set staying a single element is the check."""
    for spec in contract.ARTIFACTS.values():
        if spec.anchor is not None:
            assert spec.anchor.pdist_guard_bypass == frozenset({"OR538733"})
