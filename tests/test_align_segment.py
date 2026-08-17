"""`align.segment`: CDS splicing, the trailing-partial-codon rule, and the 6-frame fallback."""

from __future__ import annotations

import gzip
from dataclasses import replace
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align import segment as sg
from enterovirus_genbank_curated.align.population import AlignedRecord
from enterovirus_genbank_curated.contracts import ContractError

SPEC = contract.CodonSpec()


def part(ordinal: int, start: int, end: int, strand: str) -> dict:
    return {
        "part_ordinal": str(ordinal),
        "start_1based": str(start),
        "end_1based_inclusive": str(end),
        "strand": strand,
    }


# --- _finish: the trailing-partial-codon rule -----------------------------------------------------


def test_finish_drops_a_clean_trailing_stop_and_does_not_count_it_internal() -> None:
    orf, aa, n_stops = sg._finish("ATGGCCTAA")  # M A *
    assert orf == "ATGGCC"
    assert aa == "MA"
    assert n_stops == 0


def test_finish_silently_drops_one_or_two_trailing_leftover_nt() -> None:
    orf, aa, n_stops = sg._finish("ATGGCCA")  # 7 nt, one leftover
    assert orf == "ATGGCC"
    assert aa == "MA"
    assert n_stops == 0


def test_finish_counts_and_masks_an_internal_stop() -> None:
    orf, aa, n_stops = sg._finish("ATGTAAGCC")  # M * A, no trailing stop
    assert orf == "ATGTAAGCC"
    assert aa == "MXA"
    assert n_stops == 1


# --- _splice: single part, and multi-part joins -------------------------------------------------


def test_splice_single_part_forward() -> None:
    seq = "AAAACCCCGGGGTTTT"
    result = sg._splice([part(1, 1, 4, "+")], seq, "f1")
    assert result == "AAAA"


def test_splice_single_part_reverse() -> None:
    seq = "AAAACCCCGGGGTTTT"
    result = sg._splice([part(1, 1, 4, "-")], seq, "f1")
    assert result == "TTTT"  # revcomp(AAAA)


def test_splice_multipart_join_forward_concatenates_in_part_ordinal_order() -> None:
    seq = "AAAACCCCGGGGTTTT"  # 1-4=A, 5-8=C, 9-12=G, 13-16=T
    parts = [part(1, 1, 4, "+"), part(2, 9, 12, "+")]
    assert sg._splice(parts, seq, "f1") == "AAAAGGGG"


def test_splice_multipart_join_reverse_strand_per_part() -> None:
    """Each part is individually reverse-complemented per its own strand, then concatenated in
    `part_ordinal` order — reproducing `CompoundLocation.extract()` exactly (measured empirically
    against Biopython's real GenBank parser; see the module docstring)."""
    seq = "AAAAACCCCCGGGGGTTTTT"  # 1-5=A, 6-10=C, 11-15=G, 16-20=T
    # part_ordinal 1 is the later (higher-coordinate) genomic segment, matching how Biopython's
    # parser reorders .parts for a minus-strand join.
    parts = [part(1, 11, 15, "-"), part(2, 1, 5, "-")]
    assert sg._splice(parts, seq, "f1") == "CCCCC" + "TTTTT"  # revcomp(GGGGG) + revcomp(AAAAA)


def test_splice_refuses_a_feature_with_no_parts() -> None:
    with pytest.raises(ContractError, match="no location parts"):
        sg._splice([], "ACGT", "f1")


# --- _outer_span_and_strand ----------------------------------------------------------------------


def test_outer_span_and_strand_agreeing_parts() -> None:
    parts = [part(1, 5, 10, "+"), part(2, 20, 30, "+")]
    assert sg._outer_span_and_strand(parts) == (5, 30, "+")


def test_outer_span_and_strand_disagreeing_parts_is_blank() -> None:
    parts = [part(1, 5, 10, "+"), part(2, 20, 30, "-")]
    assert sg._outer_span_and_strand(parts) == (5, 30, "")


# --- _codon_start ---------------------------------------------------------------------------------


def test_codon_start_missing_is_refused() -> None:
    with pytest.raises(ContractError, match="no codon_start qualifier"):
        sg._codon_start("f1", {})


def test_codon_start_non_integer_is_refused() -> None:
    with pytest.raises(ContractError, match="not an integer"):
        sg._codon_start("f1", {"f1": "x"})


def test_codon_start_out_of_range_is_refused() -> None:
    with pytest.raises(ContractError, match="not 1, 2 or 3"):
        sg._codon_start("f1", {"f1": "4"})


@pytest.mark.parametrize("value", ["1", "2", "3"])
def test_codon_start_valid_values(value: str) -> None:
    assert sg._codon_start("f1", {"f1": value}) == int(value)


# --- _annotated: full 5'NCR / ORF / 3'NCR split, including codon_start offsets -------------------


def test_annotated_forward_strand_codon_start_1() -> None:
    # 5nt NCR + ATG GCC TAA (9nt CDS) + 4nt NCR
    seq = "AAAAA" + "ATGGCCTAA" + "TTTT"
    parts = [part(1, 6, 14, "+")]
    ncr5, ncr3, orf_nt, aa, n_stops, strand = sg._annotated(seq, "f1", parts, {"f1": "1"})
    assert ncr5 == "AAAAA"
    assert ncr3 == "TTTT"
    assert orf_nt == "ATGGCC"
    assert aa == "MA"
    assert n_stops == 0
    assert strand == "+"


def test_annotated_codon_start_offset_shifts_the_frame() -> None:
    # codon_start=2: the CDS span includes one leading nt of frame padding before the real ATG.
    seq = "AAAAA" + "XATGGCCTAA" + "TTTT"
    parts = [part(1, 6, 15, "+")]
    ncr5, ncr3, orf_nt, aa, n_stops, strand = sg._annotated(seq, "f1", parts, {"f1": "2"})
    assert orf_nt == "ATGGCC"
    assert aa == "MA"
    # ncr5 is still bounded by the outer span start, not by codon_start's internal offset.
    assert ncr5 == "AAAAA"


def test_annotated_reverse_strand() -> None:
    # Forward genome: 4nt NCR, then complement(5..13) is the CDS on minus strand, then 3nt NCR.
    # Build the CDS so its *oriented* (revcomp'd) reading is ATGGCCTAA. `_revcomp` is self-inverse,
    # so the forward-strand bases that decode to ATGGCCTAA on the minus strand are revcomp(it).
    cds_fwd = sg._revcomp("ATGGCCTAA")
    seq = "AAAA" + cds_fwd + "TTT"
    parts = [part(1, 5, 13, "-")]
    ncr5, ncr3, orf_nt, aa, n_stops, strand = sg._annotated(seq, "f1", parts, {"f1": "1"})
    assert strand == "-"
    assert orf_nt == "ATGGCC"
    assert aa == "MA"
    # oriented = revcomp(full seq); ncr5/ncr3 swap sides relative to the forward-strand genome.
    assert ncr5 == "AAA"
    assert ncr3 == "TTTT"


def test_annotated_codon_start_exceeding_spliced_length_is_refused() -> None:
    seq = "AT"
    parts = [part(1, 1, 2, "+")]  # a 2nt CDS span; codon_start=3 has nowhere to start
    with pytest.raises(ContractError, match="exceeds"):
        sg._annotated(seq, "f1", parts, {"f1": "3"})


# --- _primary_cds: longest span wins; ties keep the first-encountered feature --------------------


def test_primary_cds_picks_the_longer_span() -> None:
    features = [{"feature_id": "short"}, {"feature_id": "long"}]
    spans = {"short": (1, 10), "long": (1, 1000)}
    assert sg._primary_cds(features, spans)["feature_id"] == "long"


def test_primary_cds_ties_keep_the_first_in_list_order() -> None:
    features = [{"feature_id": "first"}, {"feature_id": "second"}]
    spans = {"first": (1, 100), "second": (1, 100)}
    assert sg._primary_cds(features, spans)["feature_id"] == "first"


# --- 6-frame inference ----------------------------------------------------------------------------


def _repeat_codon(codon: str, n: int) -> str:
    return codon * n


# The homology pool is the reference for "reads as enterovirus protein", so a unit test has to be
# able to state one. `infer_pool_min_aa` drops to 10 because these peptides are tens of residues,
# not the 600+ a real polyprotein carries; every other parameter stays at its declared value.
POOL_SPEC = replace(SPEC, infer_pool_min_aa=10)

# One codon per amino acid, so a peptide round-trips to nucleotides deterministically.
_BACK_TABLE = {}
for _codon, _residue in sorted(sg._CODON_TABLE.items()):
    _BACK_TABLE.setdefault(_residue, _codon)


def back_translate(peptide: str) -> str:
    return "".join(_BACK_TABLE[residue] for residue in peptide)


def pool_of(*proteins: str, spec: contract.CodonSpec = POOL_SPEC) -> sg.HomologyPool:
    segmentations = {
        f"P{index}": sg.Segmentation(
            accession=f"P{index}", method="annotated", strand="+", ncr5="", ncr3="",
            orf_nt=back_translate(protein), aa=protein, n_internal_stops=0, absence_reason=None,
        )
        for index, protein in enumerate(proteins)
    }
    return sg.build_homology_pool(segmentations, spec)


EMPTY = sg.EMPTY_POOL

# Two peptides over disjoint residue alphabets, so neither shares a single 6-mer with the other
# and a pool holding one of them recognises exactly one of them.
SHORT_PEPTIDE = "MKKLLVVDDEEKKLLVVDDEEKKL"  # 24 aa, over {M,K,L,V,D,E}
LONG_PEPTIDE = "MWWYYAACCTTGGWWYYAACCTTGGWWYYAACCTTGGWWYYAA"  # 43 aa, over {M,W,Y,A,C,T,G}
TWO_ORF_SEQUENCE = (
    back_translate(SHORT_PEPTIDE) + "TAA" + back_translate(LONG_PEPTIDE) + "TAA"
)


# --- _candidate_orfs: every run, not just the longest --------------------------------------------


def test_candidate_orfs_enumerates_every_stop_free_run_not_only_the_longest() -> None:
    """The old `_longest_orf` kept one run per strand and discarded the rest before anything could
    score them, which is exactly how a wrong frame could win: the true frame's run was already
    gone. Both runs of the forward frame have to survive enumeration for homology to have anything
    to choose between."""
    candidates = sg._candidate_orfs(TWO_ORF_SEQUENCE, SPEC)
    forward_frame0 = {c.aa for c in candidates if c.strand == "+" and c.frame == 0}
    assert SHORT_PEPTIDE in forward_frame0
    assert LONG_PEPTIDE in forward_frame0


def test_candidate_orfs_applies_the_length_floor_and_the_x_ceiling() -> None:
    below_floor = "ATG" + _repeat_codon("GCC", 5) + "TAA"  # 6 aa, under infer_min_aa=20
    assert sg._candidate_orfs(below_floor, SPEC) == []
    # 30 residues, half of them X from ambiguity codes -> over infer_max_x_fraction=0.4.
    x_heavy = "ATG" + _repeat_codon("GCC", 10) + _repeat_codon("NNN", 15) + "GCC" * 4 + "TAA"
    assert all(
        candidate.aa.count("X") / len(candidate.aa) <= SPEC.infer_max_x_fraction
        for candidate in sg._candidate_orfs(x_heavy, SPEC)
    )


# --- _inferred_orf: homology decides, length only breaks its ties --------------------------------


def test_inferred_orf_prefers_the_homologous_frame_over_the_longer_one() -> None:
    """The whole repair, in one assertion: the same sequence, two pools, two answers. With the
    short peptide in the pool the short run wins despite being 19 residues shorter, which the
    longest-run rule could never do."""
    result = sg._inferred_orf(TWO_ORF_SEQUENCE, SPEC, pool_of(SHORT_PEPTIDE))
    assert result is not None
    assert result[1] == SHORT_PEPTIDE

    result = sg._inferred_orf(TWO_ORF_SEQUENCE, SPEC, pool_of(LONG_PEPTIDE))
    assert result is not None
    assert result[1] == LONG_PEPTIDE


def test_inferred_orf_falls_back_to_length_when_nothing_is_homologous() -> None:
    """An empty pool scores every candidate 0.0, so the length tie-break decides — the old rule,
    now reachable only when there is genuinely no evidence. The returned homology is what
    `segment_one` reads to call the record `noncoding`."""
    result = sg._inferred_orf(TWO_ORF_SEQUENCE, SPEC, EMPTY)
    assert result is not None
    orf_nt, aa, strand, homology = result
    assert homology == 0.0
    assert len(aa) >= max(len(SHORT_PEPTIDE), len(LONG_PEPTIDE))
    assert orf_nt in (TWO_ORF_SEQUENCE if strand == "+" else sg._revcomp(TWO_ORF_SEQUENCE))


def test_inferred_orf_none_when_no_candidate_clears_the_floor() -> None:
    assert sg._inferred_orf("ATG" + _repeat_codon("GCC", 5) + "TAA", SPEC, EMPTY) is None


def test_inferred_orf_none_for_a_sequence_with_no_translatable_content() -> None:
    assert sg._inferred_orf("N" * 30, SPEC, EMPTY) is None


# --- _drop_ambiguous_runs: a padded assembly gap is not sequence ---------------------------------


def test_drop_ambiguous_runs_removes_a_long_run_and_reports_the_nucleotides() -> None:
    spec = replace(SPEC, drop_ambiguous_run_aa=5)
    head, tail = "GCC" * 6, "TTT" * 6
    orf_nt = head + "NNN" * 8 + tail
    aa = sg.translate(orf_nt)
    kept_nt, kept_aa, dropped = sg._drop_ambiguous_runs(orf_nt, aa, spec)
    assert kept_nt == head + tail
    assert kept_aa == "A" * 6 + "F" * 6
    assert dropped == 24
    assert len(kept_aa) * 3 == len(kept_nt)


def test_drop_ambiguous_runs_leaves_a_run_under_the_floor_alone() -> None:
    spec = replace(SPEC, drop_ambiguous_run_aa=5)
    orf_nt = "GCC" * 6 + "NNN" * 4 + "TTT" * 6
    aa = sg.translate(orf_nt)
    assert sg._drop_ambiguous_runs(orf_nt, aa, spec) == (orf_nt, aa, 0)


def test_drop_ambiguous_runs_reads_nucleotides_not_the_masked_stop_codon() -> None:
    """`_finish` masks an accepted internal stop to `X` too, and a stop codon is sequence. The
    predicate is over the bases, so a run of stops is never mistaken for a run of padding."""
    spec = replace(SPEC, drop_ambiguous_run_aa=3)
    orf_nt = "GCC" * 3 + "TAA" * 4 + "TTT" * 3
    aa = sg.translate(orf_nt).replace("*", "X")
    assert sg._drop_ambiguous_runs(orf_nt, aa, spec) == (orf_nt, aa, 0)


# --- _oriented_noncoding -------------------------------------------------------------------------


def test_oriented_noncoding_reverse_complements_when_the_ncr_pool_says_so() -> None:
    ncr5 = "ACGTTGCAAGGTCCATTGACGTACGTTACGGATCCATTAGGCA"
    pool = sg.build_homology_pool(
        {
            "P": sg.Segmentation(
                accession="P", method="annotated", strand="+", ncr5=ncr5, ncr3="",
                orf_nt="", aa="", n_internal_stops=0, absence_reason=None,
            )
        },
        POOL_SPEC,
    )
    oriented, strand = sg._oriented_noncoding(sg._revcomp(ncr5), pool)
    assert (oriented, strand) == (ncr5, "-")
    oriented, strand = sg._oriented_noncoding(ncr5, pool)
    assert (oriented, strand) == (ncr5, "+")


def test_oriented_noncoding_keeps_the_deposit_as_it_stands_on_a_tie() -> None:
    assert sg._oriented_noncoding("ACGTACGTACGT", EMPTY) == ("ACGTACGTACGT", "+")


# --- segment_one: the whole per-record decision tree ----------------------------------------------


def test_segment_one_annotated_when_the_cds_passes_the_gate() -> None:
    seq = "AAAAA" + "ATG" + "GCC" * 20 + "TAA" + "TTTT"
    cds_start = 6
    cds_end = cds_start + 3 + 60 + 3 - 1
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, cds_start, cds_end, "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one(
        "acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC, EMPTY
    )
    assert result.method == "annotated"
    assert result.aa == "M" + "A" * 20
    assert result.absence_reason is None
    assert result.unsequenced_nt == 0


def test_segment_one_annotated_drops_a_padded_assembly_gap_from_the_orf() -> None:
    spec = replace(SPEC, drop_ambiguous_run_aa=5)
    coding = "ATG" + "GCC" * 10 + "NNN" * 8 + "GCC" * 10 + "TAA"
    seq = coding
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, len(coding), "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one(
        "acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, spec, EMPTY
    )
    assert result.method == "annotated"
    assert result.aa == "M" + "A" * 20
    assert result.unsequenced_nt == 24
    assert len(result.aa) * 3 == len(result.orf_nt)


def test_segment_one_falls_through_to_inferred_when_the_annotated_cds_is_too_short() -> None:
    short_cds_nt = "ATG" + "GCC" * 2 + "TAA"
    seq = short_cds_nt + back_translate(LONG_PEPTIDE) + "TAA"
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, len(short_cds_nt), "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one(
        "acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC,
        pool_of(LONG_PEPTIDE),
    )
    assert result.method == "inferred"
    assert result.aa == LONG_PEPTIDE
    assert result.ncr5 == "" and result.ncr3 == ""


# A "5'UTR" for these tests is any nucleotide string the NCR pool recognises and the protein pool
# does not. The real one is 740 nt of polio 5'UTR; what matters here is which pool claims it.
UTR_LIKE = "ACGTTGCAAGGTCCATTGACGTACGTTACGGATCCATTAGGCATTCCAGGTACCATTGACCGGTTAACCGGATTCA"


def pool_with_ncr(ncr5: str, *proteins: str) -> sg.HomologyPool:
    segmentations = {
        f"P{index}": sg.Segmentation(
            accession=f"P{index}", method="annotated", strand="+", ncr5=ncr5, ncr3="",
            orf_nt=back_translate(protein), aa=protein, n_internal_stops=0, absence_reason=None,
        )
        for index, protein in enumerate(proteins)
    }
    return sg.build_homology_pool(segmentations, POOL_SPEC)


def test_segment_one_noncoding_when_an_orf_exists_but_no_frame_reads_as_protein() -> None:
    """The 1,351-row case. There is a perfectly good stop-free run here; it simply is not protein
    this corpus has ever seen, while the sequence *is* 5'UTR this corpus has seen — so the record
    keeps its sequence for the 5'NCR block instead of being handed a CDS row it did not earn."""
    seq = UTR_LIKE
    result = sg.segment_one(
        "acc", seq, "acc.1", {}, {}, {}, SPEC, pool_with_ncr(UTR_LIKE, SHORT_PEPTIDE)
    )
    assert result.method == "noncoding"
    assert result.absence_reason == sg.ABSENCE_NO_CODING_HOMOLOGY
    assert result.orf_nt == "" and result.aa == ""
    assert result.ncr5 == seq


def test_segment_one_none_when_neither_pool_recognises_the_record() -> None:
    """Not being protein is not evidence of being 5'UTR. A record neither pool claims places
    nothing at all, rather than being pushed into a covariance model that will align anything."""
    seq = back_translate(LONG_PEPTIDE) + "TAA"
    result = sg.segment_one(
        "acc", seq, "acc.1", {}, {}, {}, SPEC, pool_with_ncr(UTR_LIKE, SHORT_PEPTIDE)
    )
    assert result.method == "none"
    assert result.absence_reason == sg.ABSENCE_NO_CODING_OR_NCR_HOMOLOGY
    assert result.ncr5 == "" and result.orf_nt == ""


def test_segment_one_lets_the_ncr_pool_overrule_a_marginal_short_orf() -> None:
    """Containment over a short run has a small denominator, so a couple of chance matches can
    clear `infer_min_homology`. When the 5'NCR pool recognises the whole sequence by a wide margin
    and the protein pool only just does, the record is 5'UTR."""
    spec = replace(SPEC, infer_min_homology=0.0, noncoding_homology_margin=0.30)
    pool = pool_with_ncr(UTR_LIKE, SHORT_PEPTIDE)
    result = sg.segment_one("acc", UTR_LIKE, "acc.1", {}, {}, {}, spec, pool)
    assert result.method == "noncoding"


def test_segment_one_keeps_the_two_absence_reasons_apart() -> None:
    """`no_coding_homology` says a frame was found and read as nothing; the older two say nothing
    translatable was found at all. Same `noncoding` outcome, different findings, and the coverage
    sidecar carries whichever one is true."""
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, 9, "+")]}
    codon_starts = {"f1": "1"}
    pool = pool_with_ncr(UTR_LIKE, SHORT_PEPTIDE)

    # 76 nt: long enough for a 20 aa stop-free run to exist in some frame.
    found_an_orf = sg.segment_one(
        "acc", UTR_LIKE, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC, pool
    )
    assert found_an_orf.method == "noncoding"
    assert found_an_orf.absence_reason == sg.ABSENCE_NO_CODING_HOMOLOGY

    # 45 nt: 15 codons, so no frame can clear infer_min_aa=20 and there is no candidate at all.
    short = UTR_LIKE[:45]
    no_orf_at_all = sg.segment_one(
        "acc", short, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC, pool
    )
    assert no_orf_at_all.method == "noncoding"
    assert no_orf_at_all.absence_reason == sg.ABSENCE_ANNOTATED_REJECTED_UNTRANSLATABLE
    assert no_orf_at_all.ncr5 == short


def test_segment_one_inferred_when_there_is_no_cds_feature_at_all() -> None:
    seq = back_translate(LONG_PEPTIDE) + "TAA"
    result = sg.segment_one("acc", seq, "acc.1", {}, {}, {}, SPEC, pool_of(LONG_PEPTIDE))
    assert result.method == "inferred"
    assert result.aa == LONG_PEPTIDE


def test_segment_one_none_when_there_is_no_cds_and_neither_pool_recognises_it() -> None:
    result = sg.segment_one("acc", "N" * 10, "acc.1", {}, {}, {}, SPEC, EMPTY)
    assert result.method == "none"
    assert result.absence_reason == sg.ABSENCE_NO_CODING_OR_NCR_HOMOLOGY


# --- _boundary_cut: one amplicon spanning the 5'UTR/capsid boundary ------------------------------
#
# The `OR538737` shape. Its 897 nt read stop-free in one frame from end to end, so the whole
# deposit arrived as a single candidate ORF and the back half was real enough protein to be
# accepted -- dragging 504 nt of 5'UTR into the CDS block, where it held POLIO_unified's first 462
# columns open with no other row in any of them.
#
# A "5'UTR head" below is any nucleotide run the NCR pool recognises, whose translation the protein
# pool does not, and which carries no stop codon -- that last part being the whole rarity of the
# real case. Its residues are drawn from an alphabet disjoint from LONG_PEPTIDE's, so the two pools
# cannot both claim it.
UTR_HEAD_PEPTIDE = "PQRSNHFI" * 4  # 32 residues, over {P,Q,R,S,N,H,F,I}
UTR_HEAD_NT = back_translate(UTR_HEAD_PEPTIDE)  # 96 nt, stop-free by construction


def boundary_crossing_pool() -> sg.HomologyPool:
    """A pool that knows the head as 5'UTR and the tail as protein, and neither as the other."""
    return pool_with_ncr(UTR_HEAD_NT, LONG_PEPTIDE)


def test_boundary_cut_finds_the_join_between_a_utr_head_and_a_coding_tail() -> None:
    aa = UTR_HEAD_PEPTIDE + LONG_PEPTIDE
    orf_nt = UTR_HEAD_NT + back_translate(LONG_PEPTIDE)
    assert sg._boundary_cut(aa, orf_nt, SPEC, boundary_crossing_pool()) == len(UTR_HEAD_PEPTIDE)


def test_segment_one_sends_a_cut_utr_head_to_the_5ncr_block_and_keeps_the_tail_coding() -> None:
    """Both halves survive, each in the block that can align it. The head is not discarded and the
    tail is not left carrying it — which is the difference between this and routing the whole record
    one way or the other, the only two outcomes available before."""
    sequence = UTR_HEAD_NT + back_translate(LONG_PEPTIDE)
    result = sg.segment_one(
        "acc", sequence, "acc.1", {}, {}, {}, SPEC, boundary_crossing_pool()
    )
    assert result.method == "inferred"
    assert result.ncr5 == UTR_HEAD_NT
    assert result.aa == LONG_PEPTIDE
    assert result.orf_nt == back_translate(LONG_PEPTIDE)
    # Nothing invented and nothing lost: the two blocks partition the ORF that was accepted.
    assert result.ncr5 + result.orf_nt == sequence


def test_boundary_cut_leaves_an_intact_polyprotein_alone() -> None:
    """The negative control, and the one that matters most: 0 of 300 real annotated polyproteins
    are cut, so a synthetic one must not be either."""
    orf_nt = back_translate(LONG_PEPTIDE)
    assert sg._boundary_cut(LONG_PEPTIDE, orf_nt, SPEC, boundary_crossing_pool()) == 0


def test_boundary_cut_refuses_a_head_too_short_to_be_evidence() -> None:
    """This gate carries most of the weight. 125 of 780 inference-path records clear all three
    homology gates on a head of 5-13 codons, because some submitters annotate their CDS a few
    codons downstream of the true AUG and so a polyprotein's own first codons are *in* the 5'NCR
    pool. Measured, no record has a cut between 14 and 39 codons."""
    short_head_peptide = UTR_HEAD_PEPTIDE[:10]
    short_head_nt = back_translate(short_head_peptide)
    pool = pool_with_ncr(short_head_nt, LONG_PEPTIDE)
    aa = short_head_peptide + LONG_PEPTIDE
    orf_nt = short_head_nt + back_translate(LONG_PEPTIDE)
    assert sg._boundary_cut(aa, orf_nt, SPEC, pool) == 0
    # ...and with the floor lowered, the same head is cut, so it is the floor refusing it and not
    # some other gate happening to fail.
    assert sg._boundary_cut(aa, orf_nt, replace(SPEC, infer_min_aa=5), pool) == 10


def test_boundary_cut_refuses_a_head_neither_pool_recognises() -> None:
    """`OR538735`'s shape, and the reason this rule does not fix it. Its ORF opens with 30 residues
    the protein pool does not recognise, and the 5'NCR pool does not recognise them either — 0.000.
    Not reading as protein is not evidence of being 5'UTR, exactly as for a whole record."""
    pool = pool_with_ncr(UTR_LIKE, LONG_PEPTIDE)  # knows a 5'UTR, but not this head's
    aa = UTR_HEAD_PEPTIDE + LONG_PEPTIDE
    orf_nt = UTR_HEAD_NT + back_translate(LONG_PEPTIDE)
    assert sg._boundary_cut(aa, orf_nt, SPEC, pool) == 0


def test_boundary_cut_cannot_empty_the_orf() -> None:
    """A record that is 5'UTR from end to end is R2's case, not this one, and the two gates on the
    tail are what keep them apart. Here the changepoint runs to the full length, so the tail is
    empty: it clears neither `infer_min_aa` nor `infer_confident_homology`, and either alone is
    enough. Reaching R2 means the whole record goes to the 5'NCR block with `method` recording that
    it was never coding — not an ORF row with nothing in it."""
    aa = UTR_HEAD_PEPTIDE * 2
    orf_nt = UTR_HEAD_NT * 2
    assert sg._boundary_cut(aa, orf_nt, SPEC, pool_with_ncr(orf_nt, LONG_PEPTIDE)) == 0


def test_boundary_cut_is_a_no_op_against_an_empty_pool() -> None:
    """Pass 1 of `segment_all` runs with `EMPTY_POOL`, and no reading of it may cut anything."""
    aa = UTR_HEAD_PEPTIDE + LONG_PEPTIDE
    assert sg._boundary_cut(aa, back_translate(aa), SPEC, EMPTY) == 0


def test_a_cut_head_on_the_minus_strand_comes_back_in_the_orf_s_orientation() -> None:
    """The head is sliced off `orf_nt`, which is already oriented, so the 5'NCR block receives it
    the way round `cmalign` needs without a second orientation decision being made anywhere."""
    forward = UTR_HEAD_NT + back_translate(LONG_PEPTIDE)
    result = sg.segment_one(
        "acc", sg._revcomp(forward), "acc.1", {}, {}, {}, SPEC, boundary_crossing_pool()
    )
    assert result.method == "inferred"
    assert result.strand == "-"
    assert result.ncr5 == UTR_HEAD_NT
    assert result.aa == LONG_PEPTIDE


# --- segment_all: the real table-loading path, against tiny synthetic fixtures --------------------


def _write_tsv_gz(path: Path, header: list[str], rows: list[list[str]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        handle.write("\t".join(header) + "\n")
        for row in rows:
            handle.write("\t".join(row) + "\n")


@pytest.fixture
def fixture_root(tmp_path: Path) -> Path:
    features_path = tmp_path / contract.SOURCE_FEATURES
    parts_path = tmp_path / contract.SOURCE_FEATURE_PARTS
    qualifiers_path = tmp_path / contract.SOURCE_FEATURE_QUALIFIERS
    for path in (features_path, parts_path, qualifiers_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    _write_tsv_gz(
        features_path,
        ["feature_id", "record_id", "feature_ordinal", "feature_key", "location_parsed",
         "location_operator"],
        [
            ["ACC1.1:F1", "ACC1.1", "1", "source", "[0:100](+)", ""],
            ["ACC1.1:F2", "ACC1.1", "2", "CDS", "[5:35](+)", ""],
            ["ACC2.1:F1", "ACC2.1", "1", "source", "[0:30](+)", ""],
        ],
    )
    _write_tsv_gz(
        parts_path,
        ["feature_id", "part_ordinal", "start_1based", "end_1based_inclusive", "strand",
         "start_position_class", "end_position_class", "remote_accession"],
        [
            ["ACC1.1:F2", "1", "6", "%d", "+", "ExactPosition", "ExactPosition", ""],
        ],
    )
    _write_tsv_gz(
        qualifiers_path,
        ["feature_id", "qualifier_ordinal", "qualifier_name", "value_ordinal", "qualifier_value"],
        [
            ["ACC1.1:F2", "1", "codon_start", "1", "1"],
        ],
    )
    return tmp_path


def make_record(accession: str, sequence: str) -> AlignedRecord:
    return AlignedRecord(
        accession=accession, version=f"{accession}.1", virus_group="poliovirus", virus_type="PV1",
        family="PV", tier="backbone", sequence=sequence, length_nt=len(sequence),
    )


def test_segment_all_wires_the_real_table_loader(fixture_root: Path) -> None:
    """`ACC1`'s annotated protein is what builds the pool, and `ACC2` — the same protein with no
    CDS feature of its own — is what the pool then recognises. That is the two-pass structure in
    miniature: the annotated path never consults homology, and the inference path is judged only
    against what the annotated path produced."""
    protein = LONG_PEPTIDE * 15  # 645 aa, over the real infer_pool_min_aa of 600
    coding = back_translate(protein) + "TAA"
    seq1 = "AAAAA" + coding + "TTTT"
    seq2 = coding
    _write_tsv_gz(
        fixture_root / contract.SOURCE_FEATURE_PARTS,
        ["feature_id", "part_ordinal", "start_1based", "end_1based_inclusive", "strand",
         "start_position_class", "end_position_class", "remote_accession"],
        [["ACC1.1:F2", "1", "6", str(5 + len(coding)), "+", "ExactPosition", "ExactPosition", ""]],
    )
    records = {"ACC1": make_record("ACC1", seq1), "ACC2": make_record("ACC2", seq2)}

    results, pool = sg.segment_all(fixture_root, records)

    assert results["ACC1"].method == "annotated"
    assert results["ACC1"].aa == protein
    assert results["ACC2"].method == "inferred"
    assert results["ACC2"].aa == protein
    assert pool.n_proteins == 1


def test_segment_all_refuses_when_nothing_annotated_can_seed_the_pool(fixture_root: Path) -> None:
    """Refusing beats falling back. With no annotated protein there is no reference for "reads as
    enterovirus", and the old longest-run rule is exactly the guess this repair removed."""
    records = {"ACC2": make_record("ACC2", back_translate(LONG_PEPTIDE) + "TAA")}
    with pytest.raises(ContractError, match="infer_pool_min_aa"):
        sg.segment_all(fixture_root, records)


# --- the two copies of the same biology --------------------------------------------------------
#
# `derive/` and `align/` each carry a codon table and a complement table, and they cannot import
# each other: `align/contract.py` imports `derive/regions.py`, so the arrow only runs one way. Two
# copies of the standard genetic code is the shape that drifts, so rather than leave them uncompared
# these pin them to each other. A deliberate divergence has to delete a test to happen.


def test_the_two_codon_tables_agree() -> None:
    """`derive/evidence.py` types its 64 entries out; `align/segment.py` generates them from
    `Bio.Seq`. Both are the standard code, so a disagreement is a typo in the hand-written one."""
    from enterovirus_genbank_curated.derive.evidence import CODON_TABLE

    assert CODON_TABLE == sg._CODON_TABLE


def test_the_two_complement_tables_agree() -> None:
    """Both had the same defect — ambiguity codes other than `N` passed through uncomplemented —
    and both were fixed on 2026-08-16. Pinned so only one of them can never be fixed again."""
    from enterovirus_genbank_curated.derive import evidence

    probe = "ACGTNRYWSKMBDHVacgtnryswkmbdhv"
    assert evidence.reverse_complement(probe) == sg._revcomp(probe)


def test_the_complement_is_its_own_inverse() -> None:
    """The property that catches a mis-paired entry, which equality between two copies cannot."""
    probe = "ACGTNRYWSKMBDHV"
    assert sg._revcomp(sg._revcomp(probe)) == probe
    assert sg._revcomp("ACGTNRYWSKMBDHV") == "BDHVKMSWRYNACGT"


def test_segment_one_refuses_a_cds_annotated_across_nothing_but_padding() -> None:
    """An annotated CDS whose every codon is padding empties when the run is dropped. It must not
    reach MAFFT as a zero-length record; a record with no sequenced CDS has no CDS row."""
    spec = replace(SPEC, drop_ambiguous_run_aa=5)
    coding = "NNN" * 25
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, len(coding), "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one(
        "acc", coding, "acc.1", {"acc.1": features}, parts, codon_starts, spec, EMPTY
    )
    assert result.method == "none"
    assert result.orf_nt == "" and result.aa == ""


def test_inferred_orf_does_not_let_a_short_perfect_run_beat_a_long_polyprotein() -> None:
    """The `MT957199` defect. A 22-residue run whose every 6-mer is in the pool scores 1.000; the
    record's real 2,212-residue polyprotein scores 0.998. Ranking on recognition alone hands the
    row to the 22-mer and leaves 2,190 residues unplaced. Recognition gates, length ranks."""
    # A tail the pool has never seen, so the long run's containment is high but not perfect --
    # which is exactly the real case: 2,203 of 2,207 6-mers recognised.
    long_protein = LONG_PEPTIDE * 4 + "KKKKKK"           # 178 aa, the real ORF
    short_perfect = SHORT_PEPTIDE[:20]                   # 20 aa, every k-mer in the pool
    sequence = (
        back_translate(short_perfect) + "TAA" + back_translate(long_protein) + "TAA"
    )
    pool = pool_of(short_perfect, LONG_PEPTIDE * 4)

    short_h = pool.protein_homology(short_perfect)
    long_h = pool.protein_homology(long_protein)
    assert short_h > long_h >= SPEC.infer_confident_homology, (
        "the premise: the short run is better recognised, and both read as protein"
    )

    result = sg._inferred_orf(sequence, SPEC, pool)
    assert result is not None
    assert result[1] == long_protein, "the longer protein-reading run has to win"


def test_inferred_orf_still_refuses_a_long_run_that_does_not_read_as_protein() -> None:
    """The other half of the gate: length only ranks among candidates that clear
    `infer_confident_homology`. A long unrecognised run must not win on length alone."""
    junk = LONG_PEPTIDE * 4
    real = SHORT_PEPTIDE
    sequence = back_translate(junk) + "TAA" + back_translate(real) + "TAA"
    pool = pool_of(real)
    assert pool.protein_homology(junk) < SPEC.infer_confident_homology

    result = sg._inferred_orf(sequence, SPEC, pool)
    assert result is not None
    assert result[1] == real
