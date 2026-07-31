"""`align.stitch`: assembling 5'NCR + CDS + 3'NCR into one row per record, all-gap padding for a
record missing a block, and the coverage sidecar that explains every absence.

Pure logic throughout — no toolchain, no real cmalign/mafft output. `CodonAlignment`/`NcrBlock`
are built directly with fake `ToolResult`s the test never inspects.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, stitch
from enterovirus_genbank_curated.align.codon import CodonAlignment
from enterovirus_genbank_curated.align.population import AlignedRecord, AlignmentPopulation
from enterovirus_genbank_curated.align.runner import ToolResult
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.align.structural import NcrBlock
from enterovirus_genbank_curated.contracts import ContractError

FAKE_RESULT = ToolResult(
    tool="fake", argv=(), returncode=0, run_dir=Path("."), stdout_path=None, stderr_path=Path(".")
)

NCR_SPEC = contract.NcrSpec(
    five_prime=contract.NcrSideSpec(pop_min_nt=20, pop_max_nt=150, cm_path="unused"),
    three_prime=contract.NcrSideSpec(pop_min_nt=20, pop_max_nt=150, cm_path="unused"),
)


def make_record(accession: str, tier: str = "backbone") -> AlignedRecord:
    return AlignedRecord(
        accession=accession, version=f"{accession}.1", virus_group="poliovirus", virus_type="PV1",
        family="PV", tier=tier, sequence="N" * 10, length_nt=10,
    )


def make_segmentation(
    accession: str, method: str = "annotated", ncr5: str = "", ncr3: str = "",
    orf_nt: str = "ATGGCC", absence_reason: str | None = None,
) -> Segmentation:
    return Segmentation(
        accession=accession, method=method, strand="+", ncr5=ncr5, ncr3=ncr3, orf_nt=orf_nt,
        aa="MA" if orf_nt else "", n_internal_stops=0, absence_reason=absence_reason,
    )


def make_population(
    records: list[AlignedRecord], ncr: contract.NcrSpec = NCR_SPEC
) -> AlignmentPopulation:
    spec = contract.AlignmentSpec(
        name="TEST_unified", stack="unified",
        population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
        expected_rows=len(records), description="test fixture", ncr=ncr,
    )
    return AlignmentPopulation(spec=spec, records=tuple(records))


def make_ncr_block(
    side: str, aligned_nt: dict[str, str], width: int, ss_cons: str = ""
) -> NcrBlock:
    return NcrBlock(
        side=side, width_nt=width, aligned_nt=aligned_nt, ss_cons=ss_cons or "." * width,
        excluded_oversized=(), exec_result=FAKE_RESULT,
    )


def make_codon_alignment(aligned_nt: dict[str, str], width_aa: int) -> CodonAlignment:
    return CodonAlignment(
        width_aa=width_aa, width_nt=3 * width_aa, aligned_nt=aligned_nt, seed=tuple(aligned_nt),
        backbone_rest=(), addon=(), execs=(FAKE_RESULT,),
    )


# --- fully-populated case: every record has every block ------------------------------------------


def test_stitch_concatenates_5ncr_cds_3ncr_in_order() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", ncr5="CCCC", ncr3="TTT", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {"A": "CCCC"}, 4)
    three = make_ncr_block("3p", {"A": "TTT"}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)

    assert result.aligned_nt["A"] == "CCCC" + "ATGGCC" + "TTT"
    assert result.width_nt == 4 + 6 + 3
    assert result.width_5ncr == 4
    assert result.width_cds == 6
    assert result.width_3ncr == 3

    present = {(row.block, row.present) for row in result.coverage if row.accession == "A"}
    assert present == {("5ncr", True), ("cds", True), ("3ncr", True)}


def test_coverage_source_and_block_widths() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", ncr5="CCCC", ncr3="TT", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {"A": "CCCC"}, 4)
    three = make_ncr_block("3p", {"A": "TT-"}, 3)  # aligned width (3) can exceed source_nt (2)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)
    by_block = {row.block: row for row in result.coverage}
    assert by_block["5ncr"].source_nt == 4
    assert by_block["5ncr"].block_nt == 4
    assert by_block["3ncr"].source_nt == 2  # len(ncr3) before alignment, not the aligned width
    assert by_block["3ncr"].block_nt == 3
    assert by_block["cds"].source_nt == 6


# --- gap padding for a missing block --------------------------------------------------------------


def test_inferred_method_pads_ncr_and_records_the_inferred_reason() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", method="inferred", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {}, 4)  # no records at all on this side
    three = make_ncr_block("3p", {}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)

    assert result.aligned_nt["A"] == "-" * 4 + "ATGGCC" + "-" * 3
    by_block = {row.block: row for row in result.coverage}
    assert by_block["5ncr"].present is False
    assert by_block["5ncr"].absence_reason == stitch.REASON_INFERRED_NO_NCR
    assert by_block["3ncr"].absence_reason == stitch.REASON_INFERRED_NO_NCR
    assert by_block["cds"].present is True


def test_none_method_pads_every_block_and_reuses_segmentations_own_reason() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {
        "A": make_segmentation(
            "A", method="none", orf_nt="", absence_reason="no_cds_untranslatable"
        )
    }
    five = make_ncr_block("5p", {}, 4)
    three = make_ncr_block("3p", {}, 3)
    codon_alignment = make_codon_alignment({}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)

    assert result.aligned_nt["A"] == "-" * (4 + 6 + 3)
    by_block = {row.block: row for row in result.coverage}
    assert all(not row.present for row in result.coverage)
    assert by_block["cds"].absence_reason == "no_cds_untranslatable"
    assert by_block["5ncr"].absence_reason == "no_cds_untranslatable"
    assert by_block["3ncr"].absence_reason == "no_cds_untranslatable"


def test_annotated_but_excluded_fragment_reports_the_classifier_reason() -> None:
    """method == "annotated" and the fragment is real, but the record isn't in five_prime's
    aligned_nt (e.g. structural.py excluded it as oversized) -- the reason must come from the
    same classify_fragment predicate structural.py itself used."""
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {
        "A": make_segmentation("A", ncr5="C" * 500, ncr3="TTT", orf_nt="ATGGCC")
    }  # 500nt 5' fragment, above pop_max_nt=150
    five = make_ncr_block("5p", {}, 4)  # A excluded from the block despite a real fragment
    three = make_ncr_block("3p", {"A": "TTT"}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)
    by_block = {row.block: row for row in result.coverage}
    assert by_block["5ncr"].present is False
    assert by_block["5ncr"].absence_reason == "excluded_oversized"
    assert by_block["5ncr"].source_nt == 500


def test_absence_reason_refuses_when_block_and_classifier_disagree() -> None:
    """A record classify_fragment would call "included" but that is genuinely absent from the
    NcrBlock is an inconsistency between structural.py and the block it produced, not a case
    align.stitch should paper over."""
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", ncr5="C" * 50, ncr3="TTT", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {}, 4)  # "A" absent despite a fragment that should qualify
    three = make_ncr_block("3p", {"A": "TTT"}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    with pytest.raises(ContractError, match="the block and the classifier disagree"):
        stitch.stitch(population, segmentations, codon_alignment, five, three)


# --- row order and the RF/SS_cons consensus -------------------------------------------------------


def test_accessions_preserve_population_row_order() -> None:
    records = [make_record("ZZZ"), make_record("AAA")]  # population order, not alphabetical
    population = make_population(records)
    segmentations = {
        acc: make_segmentation(acc, ncr5="CCCC", ncr3="TTT", orf_nt="ATGGCC")
        for acc in ("ZZZ", "AAA")
    }
    five = make_ncr_block("5p", {"ZZZ": "CCCC", "AAA": "CCCC"}, 4)
    three = make_ncr_block("3p", {"ZZZ": "TTT", "AAA": "TTT"}, 3)
    codon_alignment = make_codon_alignment({"ZZZ": "ATGGCC", "AAA": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)
    assert result.accessions == ("ZZZ", "AAA")


def test_majority_rf_ties_break_on_first_encountered_row() -> None:
    """Two rows, one column tied 1-1 between A and C: Counter.most_common keeps whichever
    character it saw first, which for a single-occurrence tie is the first row's character."""
    records = [make_record("R1"), make_record("R2")]
    population = make_population(records)
    segmentations = {
        acc: make_segmentation(acc, ncr5="", ncr3="", orf_nt="ATG") for acc in ("R1", "R2")
    }
    five = make_ncr_block("5p", {}, 0)
    three = make_ncr_block("3p", {}, 0)
    # R1's CDS row is scanned first (population order), so a tie at this column favors R1's base.
    codon_alignment = make_codon_alignment({"R1": "ATG", "R2": "CTG"}, width_aa=1)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)
    assert result.rf[0] == "A"


def test_ss_cons_is_all_gap_over_the_cds_span() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", ncr5="CC", ncr3="TT", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {"A": "CC"}, 2, ss_cons="((")
    three = make_ncr_block("3p", {"A": "TT"}, 2, ss_cons="))")
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    result = stitch.stitch(population, segmentations, codon_alignment, five, three)
    assert result.ss_cons == "((" + "." * 6 + "))"


# --- error paths -------------------------------------------------------------------------------


def test_stitch_refuses_a_population_with_no_ncr_spec() -> None:
    records = [make_record("A")]
    population = make_population(records, ncr=None)
    segmentations = {"A": make_segmentation("A", orf_nt="ATGGCC")}
    five = make_ncr_block("5p", {}, 4)
    three = make_ncr_block("3p", {}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    with pytest.raises(ContractError, match="no declared NcrSpec"):
        stitch.stitch(population, segmentations, codon_alignment, five, three)


def test_stitch_refuses_mismatched_sides() -> None:
    records = [make_record("A")]
    population = make_population(records)
    segmentations = {"A": make_segmentation("A", orf_nt="ATGGCC")}
    five = make_ncr_block("3p", {}, 4)  # wrong side on purpose
    three = make_ncr_block("3p", {}, 3)
    codon_alignment = make_codon_alignment({"A": "ATGGCC"}, width_aa=2)

    with pytest.raises(ContractError, match="expected a 5p and a 3p"):
        stitch.stitch(population, segmentations, codon_alignment, five, three)
