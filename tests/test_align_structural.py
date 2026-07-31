"""`align.structural`: the NCR population window and cmalign's match-column extraction.

Pure-logic pieces (`_ncr_population`, `_match_columns`) are tested in-process — the latter against
a hand-written Stockholm fixture, no `cmalign` needed. `build_ncr_block`/`build_ncr_blocks` call
`cmalign` through `run_tool`, so their tests follow the established subprocess-per-test pattern (a
`ToolGuard` cannot be installed twice in one process — see `test_align_runner.py`'s module
docstring): real-exec tests run against the actual committed CMs in `registry/alignment_seeds/`,
using real (if short) poliovirus 3'/5' NCR sequences pulled from those CMs' own seed alignments.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, structural
from enterovirus_genbank_curated.align.segment import Segmentation

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)

SIDE_SPEC = contract.NcrSideSpec(pop_min_nt=20, pop_max_nt=150, cm_path="unused/for/pure/logic")


def make_segmentation(
    accession: str, ncr5: str = "", ncr3: str = "", method: str = "annotated"
) -> Segmentation:
    return Segmentation(
        accession=accession, method=method, strand="+", ncr5=ncr5, ncr3=ncr3, orf_nt="ATG" * 5,
        aa="M" * 5, n_internal_stops=0, absence_reason=None if method != "none" else "x",
    )


# --- classify_fragment ---------------------------------------------------------------------------


def test_classify_fragment_empty() -> None:
    assert structural.classify_fragment("", SIDE_SPEC) == structural.FRAGMENT_EMPTY


def test_classify_fragment_below_pop_min() -> None:
    assert structural.classify_fragment("A" * 5, SIDE_SPEC) == structural.FRAGMENT_BELOW_POP_MIN


def test_classify_fragment_included() -> None:
    assert structural.classify_fragment("A" * 50, SIDE_SPEC) == structural.FRAGMENT_INCLUDED


def test_classify_fragment_excluded_oversized() -> None:
    result = structural.classify_fragment("A" * 500, SIDE_SPEC)
    assert result == structural.FRAGMENT_EXCLUDED_OVERSIZED


def test_classify_fragment_no_ceiling_when_pop_max_is_none() -> None:
    spec = contract.NcrSideSpec(pop_min_nt=20, pop_max_nt=None, cm_path="unused")
    assert structural.classify_fragment("A" * 5000, spec) == structural.FRAGMENT_INCLUDED


# --- _ncr_population ------------------------------------------------------------------------------


def test_ncr_population_keeps_annotated_records_within_the_window() -> None:
    segmentations = {"a": make_segmentation("a", ncr3="A" * 50)}
    pop, excluded = structural._ncr_population(segmentations, frozenset({"a"}), "3p", SIDE_SPEC)
    assert pop == {"a": "A" * 50}
    assert excluded == ()


def test_ncr_population_drops_inferred_and_none_methods() -> None:
    segmentations = {
        "inferred": make_segmentation("inferred", ncr3="A" * 50, method="inferred"),
        "none": make_segmentation("none", ncr3="A" * 50, method="none"),
    }
    pop, _ = structural._ncr_population(
        segmentations, frozenset(segmentations), "3p", SIDE_SPEC
    )
    assert pop == {}


def test_ncr_population_drops_empty_fragments() -> None:
    segmentations = {"a": make_segmentation("a", ncr3="")}
    pop, _ = structural._ncr_population(segmentations, frozenset({"a"}), "3p", SIDE_SPEC)
    assert pop == {}


def test_ncr_population_drops_below_the_floor() -> None:
    segmentations = {"a": make_segmentation("a", ncr3="A" * 5)}  # below pop_min_nt=20
    pop, _ = structural._ncr_population(segmentations, frozenset({"a"}), "3p", SIDE_SPEC)
    assert pop == {}


def test_ncr_population_excludes_and_records_oversized_fragments() -> None:
    segmentations = {
        "short": make_segmentation("short", ncr3="A" * 50),
        "oversized": make_segmentation("oversized", ncr3="A" * 500),  # above pop_max_nt=150
    }
    pop, excluded = structural._ncr_population(
        segmentations, frozenset(segmentations), "3p", SIDE_SPEC
    )
    assert pop == {"short": "A" * 50}
    assert excluded == ("oversized",)


def test_ncr_population_no_ceiling_when_pop_max_is_none() -> None:
    spec = contract.NcrSideSpec(pop_min_nt=20, pop_max_nt=None, cm_path="unused")
    segmentations = {"a": make_segmentation("a", ncr3="A" * 5000)}
    pop, excluded = structural._ncr_population(segmentations, frozenset({"a"}), "3p", spec)
    assert pop == {"a": "A" * 5000}
    assert excluded == ()


def test_ncr_population_reads_the_correct_side() -> None:
    segmentations = {"a": make_segmentation("a", ncr5="C" * 50, ncr3="A" * 50)}
    pop5, _ = structural._ncr_population(segmentations, frozenset({"a"}), "5p", SIDE_SPEC)
    pop3, _ = structural._ncr_population(segmentations, frozenset({"a"}), "3p", SIDE_SPEC)
    assert pop5 == {"a": "C" * 50}
    assert pop3 == {"a": "A" * 50}


# --- _match_columns ---------------------------------------------------------------------------


def test_match_columns_keeps_only_non_gap_rf_columns(tmp_path: Path) -> None:
    """RF position 4 ('.') marks an insert column, dropped from every row and from SS_cons. A
    literal '.' inside a *match* column (unusual for real cmalign output, which uses '-' for a
    match-column deletion, but mechanically identical) is normalized to '-'; lowercase residues
    are uppercased."""
    sto = tmp_path / "synthetic.sto"
    sto.write_text(
        "# STOCKHOLM 1.0\n"
        "seq1                    AC-T.ACGT\n"
        "seq2                    AC.T.ACGT\n"
        "seq3                    acgt.acgt\n"
        "#=GC SS_cons            ((((.))))\n"
        "#=GC RF                 ACGT.ACGT\n"
        "//\n"
    )
    rows, ss_cons = structural._match_columns(sto)
    assert rows == {"seq1": "AC-TACGT", "seq2": "AC-TACGT", "seq3": "ACGTACGT"}
    assert ss_cons == "(((())))"


def test_match_columns_keeps_every_column_when_rf_has_no_inserts(tmp_path: Path) -> None:
    sto = tmp_path / "no_inserts.sto"
    sto.write_text(
        "# STOCKHOLM 1.0\n"
        "seq1                    ACGT\n"
        "#=GC SS_cons            ((.)\n"
        "#=GC RF                 ACGT\n"
        "//\n"
    )
    rows, ss_cons = structural._match_columns(sto)
    assert rows == {"seq1": "ACGT"}
    assert ss_cons == "((.)"


# --- build_ncr_block / build_ncr_blocks: real cmalign, subprocess-per-test -----------------------

PREAMBLE = """
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import contract, structural, scratch as sc, toolchain as tc
from enterovirus_genbank_curated.align.population import AlignedRecord, AlignmentPopulation
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.contracts import ContractError

ROOT = Path({root!r})
scratch = sc.create()
toolchain = tc.resolve(ROOT, environment=tc.ENV_ALIGN, tools=tc.ROUTINE_TOOLS, scratch=scratch.root)
guard = se.install_tool_guard(
    ROOT, scratch_root=scratch.root,
    allowed_executables=frozenset(str(t.path) for t in toolchain.tools.values()),
)


def make_record(accession, tier="backbone"):
    return AlignedRecord(
        accession=accession, version=f"{{accession}}.1", virus_group="poliovirus",
        virus_type="PV1", family="PV", tier=tier, sequence="N", length_nt=1,
    )


def make_segmentation(accession, ncr5="", ncr3="", method="annotated"):
    return Segmentation(
        accession=accession, method=method, strand="+", ncr5=ncr5, ncr3=ncr3, orf_nt="ATG",
        aa="M", n_internal_stops=0, absence_reason=None,
    )


def make_population(records, ncr):
    alignment_spec = contract.AlignmentSpec(
        name="TEST_unified", stack="unified",
        population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
        expected_rows=len(records), ncr=ncr,
    )
    return AlignmentPopulation(spec=alignment_spec, records=tuple(records))


# Two real poliovirus 3'NCR sequences (68nt), pulled and degapped from this repo's own committed
# registry/alignment_seeds/polio_ncr_3p_seed_aln.fa -- so cmalign has genuine structure to fit,
# not arbitrary bytes.
_NCR3_A = {ncr3_a!r}
_NCR3_B = {ncr3_b!r}
# Two real poliovirus 5'NCR/cloverleaf sequences (746nt), from polio_ncr_5p_seed_aln.fa.
_NCR5_A = {ncr5_a!r}
_NCR5_B = {ncr5_b!r}
"""

_NCR3_A = "TAACCCTACCTCAGTCGAATTGGATTGGGTCATACTGTTGTAGGGGTAAATTTTTCTTTAATTCGGAG"
_NCR3_B = "CAACCCTACCTCAGTCGAATTGGATTGGGTTATACTGTTGTAGGGGTAAATTTTTCTTTAATTCGGAG"
_NCR5_A = (
    "TTAAAACAGCTCTGGGGTTGTTCCCACCCCAGAGGCCCACGTGGCGGCCAGTACTCTGGTACTACGGTACCTTTGTACGCCTGTTTTATA"
    "CTCCCTCCCCCATGCAACATTAGAAGCAATTCACAAAGTTCAATAGAGGGGGTACAAACCAGTACCACCACGAACAAGCACTTCTGTTTC"
    "CCCGGTGATCTCGTATAGGCCGTACCCACGGCTGAAAACAAGTGATCCGTTATCCGCTTAGGTACTTCGAGAAACCTAGTATCACCTTGG"
    "GATCTTCGACGCGTTGCACTCAGCACTCTACCCCGAGTGTAGCTTAGGCTGATGAGTCTGGGCATTCCCCACCGGTGACGGTGGCCCAGG"
    "CTGCGTTGGCGGCCTACCCATGGCTAACGCCATGGGACGCTAGTTGTGAACAAGGTGTGAAGAGCCTATTGAGCTACCTAAGAGTCCTCC"
    "GGCCCCTGAATGCGGCTAATCCCAACCACGGAGCAAGTGCCTTCAATCCAGAGGGTGGCTTGTCGTAACGCGCAAGTCTGTGGCGGAACC"
    "GACTACTTTGGGTGTCCGTGTTTCCTTTTATTTTTATTACGGCTGCTTATGGTGACAATCATTGATTGCCATCATAAAGCGAGTTGGATT"
    "GGCCATCCGGTGAAAGTTAAGTATCTCGTCCACTTATCTGTTGGACTTACTCCATTAACTCAACTCACGCCTGATTTGATATCTATAGTG"
    "TTATTGATTTGGAAAAAGCTATCATA"
)
_NCR5_B = (
    "TTAAAACAGCTCTGGGGTTGTTCCCACCCCAGAGGCCCACGTGGCGGCCAGTACTCTGGTACTACGGTACCTTTGTACGCCTGTTTTATA"
    "CCCCCTCCCCCATGCAACCTTAGAAGCAATTCACAAAGTTCAATAGAGGGGGTACAAACCAGTACCAACACGAACAAGCACTTCTGTTTC"
    "CCCGGTGATCTCGTATAGGCTGTACCCACGGCTGAAAACAAGTGATCCGTTATCCGCTTAGGTACTTCGAGAAGCCTAGTACCACCTTGG"
    "GATCTTCGACGCGTTGCACTCAGCACTCTACCCCGAGTGTAGCTTAGGCTGATGAGCCTGGGCATTCCCCACCGGTGACGGTGGCCCAGG"
    "CTGCGTTGGCGGCCTACCCATGGCTAACGCCATGGGACGCTAGTTGTGAACAAGGTGTGAAGAGCCTATTGAGCTACCTAAGAGTCCTCC"
    "GGCCCCTGAATGCGGCTAATCCCAACCACGGAGCAAGTGCCTTCAATCCAGAGGGTGGCTTGTCGTAACGCGCAAGTCTGTGGCGGAACC"
    "GACTACTTTGGGTGTCCGTGTTTCCTTTTATTTTTATTACGGCTGCTTATGGTGACAATCATTGATTGCCATCATAAAGCGAGTTGGATT"
    "GGCCATCCGGTGAAAGTTGAGTATCTCGTCCACTTATCTGTTGGATTTCCCCTATTAACTCAACTCACGCCTGTTTTGATATCTATAGTG"
    "TTATTGATTTGGAAAAAGCTATCATA"
)


def run_real(repository_root: Path, body: str) -> subprocess.CompletedProcess[str]:
    preamble = PREAMBLE.format(
        root=str(repository_root), ncr3_a=_NCR3_A, ncr3_b=_NCR3_B, ncr5_a=_NCR5_A, ncr5_b=_NCR5_B,
    )
    script = preamble + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, cwd=repository_root, timeout=120,
    )


def assert_clean(result: subprocess.CompletedProcess[str]) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode == 0, f"expected a clean run:\n{combined}"


def assert_refused(result: subprocess.CompletedProcess[str], fragment: str) -> None:
    combined = result.stdout + result.stderr
    assert result.returncode != 0, f"expected a refusal:\n{combined}"
    assert fragment in combined, f"expected {fragment!r} in:\n{combined}"


@REQUIRES_ENV
def test_build_ncr_block_3p_runs_against_the_real_committed_cm(repository_root: Path) -> None:
    body = """
    ncr = contract.NcrSpec(
        five_prime=contract.NcrSideSpec(50, 1000, "registry/alignment_seeds/polio_ncr_5p.cm"),
        three_prime=contract.NcrSideSpec(20, 150, "registry/alignment_seeds/polio_ncr_3p.cm"),
    )
    population = make_population([make_record("A"), make_record("B")], ncr)
    segmentations = {
        "A": make_segmentation("A", ncr3=_NCR3_A),
        "B": make_segmentation("B", ncr3=_NCR3_B),
    }
    block = structural.build_ncr_block(
        population, "3p", segmentations, ncr.three_prime, toolchain, scratch, guard, ROOT,
        threads=1, timeout_s=60, index=0,
    )
    assert set(block.aligned_nt) == {"A", "B"}
    assert block.side == "3p"
    for row in block.aligned_nt.values():
        assert len(row) == block.width_nt
    assert len(block.ss_cons) == block.width_nt
    assert block.excluded_oversized == ()
    se.assert_no_violations(guard)
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_build_ncr_blocks_runs_both_sides(repository_root: Path) -> None:
    body = """
    ncr = contract.NcrSpec(
        five_prime=contract.NcrSideSpec(50, 1000, "registry/alignment_seeds/polio_ncr_5p.cm"),
        three_prime=contract.NcrSideSpec(20, 150, "registry/alignment_seeds/polio_ncr_3p.cm"),
    )
    population = make_population([make_record("A"), make_record("B")], ncr)
    segmentations = {
        "A": make_segmentation("A", ncr5=_NCR5_A, ncr3=_NCR3_A),
        "B": make_segmentation("B", ncr5=_NCR5_B, ncr3=_NCR3_B),
    }
    five, three = structural.build_ncr_blocks(
        population, segmentations, toolchain, scratch, guard, ROOT, threads=1, timeout_s=60,
    )
    assert five.side == "5p"
    assert three.side == "3p"
    assert set(five.aligned_nt) == {"A", "B"}
    assert set(three.aligned_nt) == {"A", "B"}
    se.assert_no_violations(guard)
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_build_ncr_block_refuses_an_empty_population_window(repository_root: Path) -> None:
    body = """
    ncr = contract.NcrSpec(
        five_prime=contract.NcrSideSpec(50, 1000, "registry/alignment_seeds/polio_ncr_5p.cm"),
        three_prime=contract.NcrSideSpec(20, 150, "registry/alignment_seeds/polio_ncr_3p.cm"),
    )
    population = make_population([make_record("A")], ncr)
    # method="inferred" -- carries no NCR content at all -- so the 3p population is empty.
    segmentations = {"A": make_segmentation("A", ncr3=_NCR3_A, method="inferred")}
    structural.build_ncr_block(
        population, "3p", segmentations, ncr.three_prime, toolchain, scratch, guard, ROOT,
        threads=1, timeout_s=60, index=0,
    )
    """
    assert_refused(run_real(repository_root, body), "no record in the declared population window")


@REQUIRES_ENV
def test_build_ncr_block_excludes_an_oversized_fragment_without_crashing(
    repository_root: Path,
) -> None:
    body = """
    ncr = contract.NcrSpec(
        five_prime=contract.NcrSideSpec(50, 1000, "registry/alignment_seeds/polio_ncr_5p.cm"),
        three_prime=contract.NcrSideSpec(20, 150, "registry/alignment_seeds/polio_ncr_3p.cm"),
    )
    population = make_population([make_record("A"), make_record("OVERSIZED")], ncr)
    segmentations = {
        "A": make_segmentation("A", ncr3=_NCR3_A),
        "OVERSIZED": make_segmentation("OVERSIZED", ncr3="A" * 500),
    }
    block = structural.build_ncr_block(
        population, "3p", segmentations, ncr.three_prime, toolchain, scratch, guard, ROOT,
        threads=1, timeout_s=60, index=0,
    )
    assert set(block.aligned_nt) == {"A"}
    assert block.excluded_oversized == ("OVERSIZED",)
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout
