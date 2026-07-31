"""`align.segment`: CDS splicing, the trailing-partial-codon rule, and the 6-frame fallback."""

from __future__ import annotations

import gzip
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


def test_longest_orf_keeps_the_longest_stop_free_segment_in_any_frame() -> None:
    # frame0 "TAA ATG GCC TAA GCC" splits into segments "MA"/"A" (len 2). frame1 "AAA TGG CCT AAG"
    # is stop-free, len 4 ("KWPK"). frame2 "AAT GGC CTA AGC" is also stop-free, len 4 ("NGLS") but
    # found second, so frame1's equal-length segment wins the strict `>` tie-break.
    oriented = "TAAATGGCCTAAGCC"
    assert sg._longest_orf(oriented) == (4, "AAATGGCCTAAG", "KWPK")


def test_inferred_orf_picks_the_longer_of_the_two_orientations() -> None:
    """`_inferred_orf`'s only job beyond scanning each orientation with `_longest_orf` is to keep
    whichever side is longer and apply the floor/ceiling gates. Which of 6 frame/strand
    combinations reads stop-free longest on an organic-looking sequence is genuinely not
    predictable by hand (measured, not assumed: an earlier version of this test guessed wrong) —
    so derive the expected winner from `_longest_orf` itself, independently verified above,
    instead of hardcoding a guessed strand."""
    seq = "ATG" + "AAAGAAGATCTGTCTGTTATTCCACGTACC" * 4 + "TAA"
    forward_best = sg._longest_orf(seq)
    reverse_best = sg._longest_orf(sg._revcomp(seq))
    assert forward_best is not None
    assert reverse_best is not None

    result = sg._inferred_orf(seq, SPEC)
    assert result is not None
    orf_nt, aa, strand = result

    winner = forward_best if forward_best[0] >= reverse_best[0] else reverse_best
    assert strand == ("+" if forward_best[0] >= reverse_best[0] else "-")
    assert orf_nt == winner[1]
    assert aa == winner[2]
    assert len(aa) >= SPEC.infer_min_aa


def test_inferred_orf_none_when_too_short() -> None:
    seq = "ATG" + _repeat_codon("GCC", 5) + "TAA"  # 6 aa, below infer_min_aa=20
    assert sg._inferred_orf(seq, SPEC) is None


def test_inferred_orf_none_when_too_x_heavy() -> None:
    # 30 aa total, more than 40% translate to X (ambiguity codes).
    seq = "ATG" + _repeat_codon("GCC", 10) + _repeat_codon("NNN", 15) + "GCC" * 5 + "TAA"
    assert sg._inferred_orf(seq, SPEC) is None


def test_inferred_orf_none_for_a_sequence_with_no_translatable_content() -> None:
    assert sg._inferred_orf("N" * 30, SPEC) is None


# --- segment_one: the whole per-record decision tree ----------------------------------------------


def test_segment_one_annotated_when_the_cds_passes_the_gate() -> None:
    seq = "AAAAA" + "ATG" + "GCC" * 20 + "TAA" + "TTTT"
    cds_start = 6
    cds_end = cds_start + 3 + 60 + 3 - 1
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, cds_start, cds_end, "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one("acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC)
    assert result.method == "annotated"
    assert result.aa == "M" + "A" * 20
    assert result.absence_reason is None


def test_segment_one_falls_through_to_inferred_when_the_annotated_cds_is_too_short() -> None:
    # short_cds_nt translates to 3 aa (M + 2*A), below accept_annotated_min_aa=20, so the
    # annotated frame is rejected and inference takes over the whole sequence including the long
    # tail. Which of 6 frame/strand combinations reads longest there isn't asserted here (see
    # test_inferred_orf_picks_the_longer_of_the_two_orientations for that) — only that inference
    # found *something* long enough to accept.
    short_cds_nt = "ATG" + "GCC" * 2 + "TAA"
    long_orf_nt = "ATG" + "GCC" * 30 + "TAA"
    seq = short_cds_nt + long_orf_nt
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, len(short_cds_nt), "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one("acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC)
    assert result.method == "inferred"
    assert len(result.aa) >= SPEC.infer_min_aa
    assert result.ncr5 == "" and result.ncr3 == ""


def test_segment_one_none_when_annotated_cds_rejected_and_inference_also_fails() -> None:
    seq = "N" * 30
    features = [{"feature_id": "f1", "feature_ordinal": "1"}]
    parts = {"f1": [part(1, 1, 9, "+")]}
    codon_starts = {"f1": "1"}
    result = sg.segment_one("acc", seq, "acc.1", {"acc.1": features}, parts, codon_starts, SPEC)
    assert result.method == "none"
    assert result.absence_reason == sg.ABSENCE_ANNOTATED_REJECTED_UNTRANSLATABLE


def test_segment_one_inferred_when_there_is_no_cds_feature_at_all() -> None:
    seq = "ATG" + "GCC" * 30 + "TAA"
    result = sg.segment_one("acc", seq, "acc.1", {}, {}, {}, SPEC)
    assert result.method == "inferred"


def test_segment_one_none_when_there_is_no_cds_and_inference_fails() -> None:
    seq = "N" * 10
    result = sg.segment_one("acc", seq, "acc.1", {}, {}, {}, SPEC)
    assert result.method == "none"
    assert result.absence_reason == sg.ABSENCE_NO_CDS_UNTRANSLATABLE


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
            ["ACC1.1:F2", "1", "6", "71", "+", "ExactPosition", "ExactPosition", ""],
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


def test_segment_all_wires_the_real_table_loader(fixture_root: Path) -> None:
    seq1 = "AAAAA" + "ATG" + "GCC" * 20 + "TAA" + "TTTT"  # matches parts 6..35 above
    seq2 = "ATG" + "GCC" * 30 + "TAA"  # no CDS feature at all -> inference path
    records = {
        "ACC1": AlignedRecord(
            accession="ACC1", version="ACC1.1", virus_group="poliovirus", virus_type="PV1",
            family="PV", tier="backbone", sequence=seq1, length_nt=len(seq1),
        ),
        "ACC2": AlignedRecord(
            accession="ACC2", version="ACC2.1", virus_group="poliovirus", virus_type="PV1",
            family="PV", tier="backbone", sequence=seq2, length_nt=len(seq2),
        ),
    }
    results = sg.segment_all(fixture_root, records)
    assert results["ACC1"].method == "annotated"
    assert results["ACC1"].aa == "M" + "A" * 20
    assert results["ACC2"].method == "inferred"
    assert len(results["ACC2"].aa) >= SPEC.infer_min_aa
