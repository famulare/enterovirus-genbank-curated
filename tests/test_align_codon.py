"""`align.codon`: tier splitting, seed selection, and the AA<->codon backtranslation invariant.

Pure-logic pieces (`_aa_by_tier`, `choose_seed`, `backtranslate`) are tested in-process with fake
population/segmentation fixtures — no toolchain needed. `build_codon_block` itself calls `mafft`
through `run_tool`, so its tests follow `test_align_runner.py`'s subprocess-per-test pattern: a
`ToolGuard` cannot be installed twice in one process (see that file's module docstring), so each
real-exec test runs in its own interpreter.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import codon, contract
from enterovirus_genbank_curated.align.population import AlignedRecord, AlignmentPopulation
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.contracts import ContractError

REQUIRES_ENV = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / ".pixi/envs/align/bin/mafft").exists(),
    reason="pixi align environment is not installed; run `pixi install --locked -e align`",
)

SPEC = contract.CodonSpec(seed_min_aa=10, seed_per_type=1)


def make_record(accession: str, virus_type: str, tier: str) -> AlignedRecord:
    return AlignedRecord(
        accession=accession, version=f"{accession}.1", virus_group="poliovirus",
        virus_type=virus_type, family="PV", tier=tier, sequence="A" * 30, length_nt=30,
    )


def make_segmentation(accession: str, aa: str, method: str = "annotated") -> Segmentation:
    orf_nt = "ATG" * len(aa) if aa else ""
    return Segmentation(
        accession=accession, method=method, strand="+", ncr5="", ncr3="", orf_nt=orf_nt, aa=aa,
        n_internal_stops=0,
        absence_reason=None if method != "noncoding" else "no_cds_untranslatable",
    )


def make_population(
    records: list[AlignedRecord], spec: contract.CodonSpec = SPEC
) -> AlignmentPopulation:
    alignment_spec = contract.AlignmentSpec(
        name="TEST_unified", stack="unified",
        population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
        expected_rows=len(records), description="test fixture", codon=spec,
    )
    return AlignmentPopulation(spec=alignment_spec, records=tuple(records))


# --- _aa_by_tier -------------------------------------------------------------------------------


def test_aa_by_tier_splits_backbone_and_addon_and_drops_noncoding() -> None:
    records = [
        make_record("BB1", "PV1", "backbone"),
        make_record("AD1", "PV1", "addon"),
        make_record("NONCODING1", "PV1", "backbone"),
    ]
    population = make_population(records)
    segmentations = {
        "BB1": make_segmentation("BB1", "M" * 15),
        "AD1": make_segmentation("AD1", "M" * 5),
        "NONCODING1": make_segmentation("NONCODING1", "", method="noncoding"),
    }
    backbone, addon = codon._aa_by_tier(population, segmentations)
    assert backbone == {"BB1": "M" * 15}
    assert addon == {"AD1": "M" * 5}


# --- choose_seed --------------------------------------------------------------------------------


def test_choose_seed_requires_backbone_tier_and_the_aa_floor() -> None:
    records = [make_record("BB1", "PV1", "backbone"), make_record("AD1", "PV1", "addon")]
    population = make_population(records)
    backbone_aa = {"BB1": "M" * 15}  # AD1 never enters backbone_aa at all
    assert codon.choose_seed(population, backbone_aa, SPEC) == ("BB1",)


def test_choose_seed_excludes_records_below_seed_min_aa() -> None:
    records = [make_record("SHORT", "PV1", "backbone")]
    population = make_population(records)
    backbone_aa = {"SHORT": "M" * 5}  # below seed_min_aa=10
    assert codon.choose_seed(population, backbone_aa, SPEC) == ()


def test_choose_seed_keeps_top_n_per_type_by_length() -> None:
    records = [
        make_record("LONG", "PV1", "backbone"),
        make_record("MEDIUM", "PV1", "backbone"),
        make_record("SHORT_BUT_QUALIFIES", "PV1", "backbone"),
    ]
    population = make_population(records)
    backbone_aa = {"LONG": "M" * 30, "MEDIUM": "M" * 20, "SHORT_BUT_QUALIFIES": "M" * 10}
    spec = contract.CodonSpec(seed_min_aa=10, seed_per_type=2)
    assert codon.choose_seed(population, backbone_aa, spec) == ("LONG", "MEDIUM")


def test_choose_seed_ties_break_on_accession_not_insertion_order() -> None:
    """Both records tie at the same aa length; ZZZ is appended to the per-type list before AAA
    (constructed deliberately), so a selection that only sorted on `-len` would keep whichever
    came first in iteration order. The accession secondary key must pick AAA regardless."""
    records = [
        make_record("ZZZ", "PV1", "backbone"),
        make_record("AAA", "PV1", "backbone"),
    ]
    population = make_population(records)
    backbone_aa = {"ZZZ": "M" * 15, "AAA": "M" * 15}
    assert codon.choose_seed(population, backbone_aa, SPEC) == ("AAA",)


def test_choose_seed_groups_blank_type_under_its_sentinel() -> None:
    records = [make_record("BLANK1", "", "backbone")]
    population = make_population(records)
    backbone_aa = {"BLANK1": "M" * 15}
    # Groups under the PV? sentinel rather than crashing on an empty-string type key.
    assert codon.choose_seed(population, backbone_aa, SPEC) == ("BLANK1",)


# --- backtranslate ------------------------------------------------------------------------------


def test_backtranslate_maps_gaps_to_codon_gaps_and_residues_to_their_codon() -> None:
    aa_aln = {"acc": "M-A"}
    orf_nt = {"acc": "ATGGCC"}  # M, A -> 2 codons, matching the 2 non-gap residues
    result = codon.backtranslate(aa_aln, orf_nt, width_aa=3)
    assert result == {"acc": "ATG---GCC"}


def test_backtranslate_refuses_when_the_codon_count_does_not_match() -> None:
    aa_aln = {"acc": "MA"}  # 2 non-gap residues
    orf_nt = {"acc": "ATGGCCGGG"}  # 3 codons -- mismatched
    with pytest.raises(ContractError, match="AA<->codon invariant"):
        codon.backtranslate(aa_aln, orf_nt, width_aa=2)


def test_backtranslate_refuses_a_non_whole_codon_orf_even_if_floor_division_would_match() -> None:
    """Upstream's own check (`nongap == len(nt) // 3`) would accept this: 2 nongap residues,
    8 nt, 8 // 3 == 2. The exact check here (`nongap * 3 == len(nt)`) must not."""
    aa_aln = {"acc": "MA"}
    orf_nt = {"acc": "A" * 8}
    with pytest.raises(ContractError, match="AA<->codon invariant"):
        codon.backtranslate(aa_aln, orf_nt, width_aa=2)


def test_backtranslate_refuses_a_width_aa_mismatch() -> None:
    aa_aln = {"acc": "MA"}
    orf_nt = {"acc": "ATGGCC"}
    with pytest.raises(ContractError, match="backtranslated width"):
        codon.backtranslate(aa_aln, orf_nt, width_aa=5)


# --- build_codon_block: real mafft, subprocess-per-test -----------------------------------------

PREAMBLE = """
from pathlib import Path
from enterovirus_genbank_curated import sandbox_exec as se
from enterovirus_genbank_curated.align import codon, contract, scratch as sc, toolchain as tc
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


def make_record(accession, virus_type, tier, sequence):
    return AlignedRecord(
        accession=accession, version=f"{{accession}}.1", virus_group="poliovirus",
        virus_type=virus_type, family="PV", tier=tier, sequence=sequence, length_nt=len(sequence),
    )


def make_segmentation(accession, aa, orf_nt, method="annotated"):
    return Segmentation(
        accession=accession, method=method, strand="+", ncr5="", ncr3="", orf_nt=orf_nt, aa=aa,
        n_internal_stops=0, absence_reason=None,
    )


def make_population(records, spec):
    alignment_spec = contract.AlignmentSpec(
        name="TEST_unified", stack="unified",
        population=contract.PopulationSpec(virus_groups=(contract.POLIOVIRUS,)),
        expected_rows=len(records), description="test fixture", codon=spec,
    )
    return AlignmentPopulation(spec=alignment_spec, records=tuple(records))


_ORF_A = {orf_a!r}
_ORF_B = {orf_b!r}
"""


def run_real(repository_root: Path, body: str) -> subprocess.CompletedProcess[str]:
    preamble = PREAMBLE.format(root=str(repository_root), orf_a=_ORF_A, orf_b=_ORF_B)
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


# Two clean protein-coding ORFs, long enough to satisfy a seed_min_aa floor and short enough for
# mafft-linsi to align in well under a second. Deliberately different lengths (not just different
# accessions) so a `seed_per_type=1` selection between them is unambiguous — a length *tie* is
# exercised separately by test_choose_seed_ties_break_on_accession_not_insertion_order.
_ORF_A = "ATG" + "AAAGAAGATCTGTCTGTTATTCCACGTACC" * 2 + "TAA"  # 21 aa
_ORF_B = "ATG" + "GATCTGTCTGTTATTCCACGTACCAAAGAA" + "TAA"  # 11 aa


@REQUIRES_ENV
def test_build_codon_block_seed_only_runs_end_to_end(repository_root: Path) -> None:
    """No backbone-rest, no addon -- exercises the seed-only path (one mafft-linsi call, no
    pass1/pass2), and confirms the backtranslated nucleotide alignment matches width_nt == 3 *
    width_aa with every declared record present."""
    body = """
    from Bio.Seq import Seq
    aa_a = str(Seq(_ORF_A).translate())[:-1]
    aa_b = str(Seq(_ORF_B).translate())[:-1]
    spec = contract.CodonSpec(seed_min_aa=5, seed_per_type=2)
    records = [
        make_record("SEEDA", "PV1", "backbone", "N" * 30),
        make_record("SEEDB", "PV1", "backbone", "N" * 30),
    ]
    population = make_population(records, spec)
    segmentations = {
        "SEEDA": make_segmentation("SEEDA", aa_a, _ORF_A[:-3]),
        "SEEDB": make_segmentation("SEEDB", aa_b, _ORF_B[:-3]),
    }
    result = codon.build_codon_block(
        population, segmentations, toolchain, scratch, guard, ROOT, threads=1, timeout_s=120,
    )
    assert set(result.aligned_nt) == {"SEEDA", "SEEDB"}
    assert set(result.seed) == {"SEEDA", "SEEDB"}
    assert result.backbone_rest == ()
    assert result.addon == ()
    assert len(result.execs) == 1
    for row in result.aligned_nt.values():
        assert len(row) == result.width_nt
        assert result.width_nt == 3 * result.width_aa
    se.assert_no_violations(guard)
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_build_codon_block_runs_all_three_stages(repository_root: Path) -> None:
    """One seed record, one backbone-rest record (pass1, --add), one addon record (pass2,
    --addfragments) -- the full three-stage path."""
    body = """
    from Bio.Seq import Seq
    aa_a = str(Seq(_ORF_A).translate())[:-1]
    aa_b = str(Seq(_ORF_B).translate())[:-1]
    aa_fragment = aa_a[:6]
    fragment_nt = _ORF_A[:-3][:18]
    spec = contract.CodonSpec(seed_min_aa=5, seed_per_type=1)
    records = [
        make_record("SEED", "PV1", "backbone", "N" * 30),
        make_record("REST", "PV1", "backbone", "N" * 30),
        make_record("ADDON", "PV1", "addon", "N" * 12),
    ]
    population = make_population(records, spec)
    segmentations = {
        "SEED": make_segmentation("SEED", aa_a, _ORF_A[:-3]),
        "REST": make_segmentation("REST", aa_b, _ORF_B[:-3]),
        "ADDON": make_segmentation("ADDON", aa_fragment, fragment_nt),
    }
    result = codon.build_codon_block(
        population, segmentations, toolchain, scratch, guard, ROOT, threads=1, timeout_s=120,
    )
    assert result.seed == ("SEED",)
    assert result.backbone_rest == ("REST",)
    assert result.addon == ("ADDON",)
    assert set(result.aligned_nt) == {"SEED", "REST", "ADDON"}
    assert len(result.execs) == 3
    for row in result.aligned_nt.values():
        assert len(row) == result.width_nt
    se.assert_no_violations(guard)
    print("ALL PASS")
    """
    result = run_real(repository_root, body)
    assert_clean(result)
    assert "ALL PASS" in result.stdout


@REQUIRES_ENV
def test_build_codon_block_refuses_when_no_record_reaches_the_seed_floor(
    repository_root: Path,
) -> None:
    body = """
    spec = contract.CodonSpec(seed_min_aa=10_000, seed_per_type=1)
    records = [make_record("BB1", "PV1", "backbone", "N" * 30)]
    population = make_population(records, spec)
    segmentations = {"BB1": make_segmentation("BB1", "M" * 20, "ATG" * 20)}
    codon.build_codon_block(
        population, segmentations, toolchain, scratch, guard, ROOT, threads=1, timeout_s=120,
    )
    """
    assert_refused(run_real(repository_root, body), "no exemplar to seed a backbone from")


# --- unsequenced codon columns -------------------------------------------------------------------
#
# Added 2026-08-15. `mafft --addfragments` opens a column for an N-run because an N-run *is* an
# insertion as far as the aligner can tell, and eleven deposits with assembly gaps padded to full
# length were holding open 7,130 all-N columns in `NPEV_unified` — 48.8% of its CDS block.


def test_a_codon_column_no_record_sequenced_is_dropped() -> None:
    kept, dropped = codon.drop_unsequenced_codon_columns(
        {"a": "ACGNNNACG", "b": "ACGNNNACG", "c": "ACG---ACG"}, 3
    )
    assert dropped == 1
    assert kept == {"a": "ACGACG", "b": "ACGACG", "c": "ACGACG"}


def test_one_sequenced_base_keeps_the_column() -> None:
    """The filter's whole claim is that nothing readable is discarded, so one base is enough."""
    kept, dropped = codon.drop_unsequenced_codon_columns(
        {"a": "ACGNNNACG", "b": "ACGNNGACG"}, 3
    )
    assert dropped == 0
    assert kept == {"a": "ACGNNNACG", "b": "ACGNNGACG"}


def test_an_empty_column_is_not_an_unsequenced_one() -> None:
    """A gap column is left alone. Dropping it would quietly change this from "nobody sequenced
    it" to "nobody used it", which is a different and much larger claim."""
    rows = {"a": "ACG---ACG", "b": "ACG---ACG"}
    assert codon.drop_unsequenced_codon_columns(rows, 3) == (rows, 0)


def test_the_width_stays_a_whole_number_of_codons() -> None:
    """Dropping at codon granularity is what keeps `backtranslate`'s frame intact — a single-column
    filter would shift every downstream codon by one."""
    kept, dropped = codon.drop_unsequenced_codon_columns(
        {"a": "NNNACGNNN", "b": "NNNACGNNN"}, 3
    )
    assert dropped == 2
    assert all(len(row) % 3 == 0 for row in kept.values())
    assert kept == {"a": "ACG", "b": "ACG"}


def test_emptying_a_row_is_refused_rather_than_shipped() -> None:
    """A row that is `present` and all-gap fails `validation/alignment.py` outright, so this stops
    at the point the information is still available to explain why."""
    # `a` occupies exactly one column and it is all-N, so the filter would leave it all-gap.
    with pytest.raises(ContractError, match="no sequenced CDS"):
        codon.drop_unsequenced_codon_columns({"a": "NNN---", "b": "---ACG"}, 2)


def test_a_row_reduced_to_nothing_is_caught_too() -> None:
    """The empty-string case, which a truthiness guard skips. Every column goes here, so the rows
    do not become all-gap — they become nothing at all, and that must not ship either."""
    with pytest.raises(ContractError, match="no sequenced CDS"):
        codon.drop_unsequenced_codon_columns({"a": "NNN", "b": "NNN"}, 1)


# --- the fling: a cluster parked far from its own row --------------------------------------------
#
# `KM486565`'s protein reads `DNNTHSL|QGSTVKD...` and MAFFT put those first seven residues 558
# columns from the rest of it, on columns whose consensus reads `SDRVMQL`. Ten of the eighteen
# affected rows are EV-B77 from one submission, so the stretched span reports as a serotype-wide
# deletion. See `CodonSpec.fling_min_identity` for the measured separation these tests stand on:
# under this code's own definition, 34 candidate clusters score 0.000-0.333 and 9 score 0.667-0.955,
# and 0.50 sits almost exactly at the midpoint of that empty interval.

GAP = "-"
SPLIT = contract.CodonSpec().fling_split_codons
BODY = "MKLVDE" * 12  # 72 residues, enough that a 7-residue cluster is under fling_max_share


def flung_block(tail: str, crowd_tail: str = "ACDEFGH", crowd: int = 20) -> dict[str, str]:
    """Every row gets the same body and a distant tail; `subject`'s tail is the one that differs."""
    block = {f"crowd{index}": BODY + GAP * SPLIT + crowd_tail for index in range(crowd)}
    block["subject"] = BODY + GAP * SPLIT + tail
    return block


def orfs_for(block: dict[str, str]) -> dict[str, str]:
    return {name: "GCC" * (len(row) - row.count(GAP)) for name, row in block.items()}


def test_a_cluster_that_agrees_with_nothing_is_gapped() -> None:
    block = flung_block("WWWWWWW")
    orfs = orfs_for(block)
    kept, trimmed, gapped, columns = codon.gap_flung_clusters(
        block, orfs, contract.CodonSpec()
    )
    assert gapped == {"subject": 7}
    assert set(kept["subject"][-7:]) == {GAP}
    assert kept["crowd0"][-7:] == "ACDEFGH"
    # The ORF is cut in step, which is the invariant `backtranslate` rests on.
    assert len(trimmed["subject"]) == len(orfs["subject"]) - 21
    assert columns == 0


def test_a_distant_cluster_that_agrees_is_left_alone() -> None:
    """The negative control that matters: nine real bipartite fragments land far from their own
    other half and score 0.667-0.955, and gapping them would delete real homologous sequence.
    Distance proposes; identity decides."""
    block = flung_block("ACDEFGH")
    kept, trimmed, gapped, columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    assert gapped == {}
    assert kept == block
    assert columns == 0


def test_a_cluster_that_is_most_of_its_row_is_not_a_fling() -> None:
    """Without the share cap the two modes stop being separable at all — the widest empty interval
    collapses from (0.333, 0.667) to a third of that. A cluster that is most of its own row is the
    row, whatever it agrees with."""
    block = {f"crowd{index}": "MK" + GAP * SPLIT + "ACDEFGH" for index in range(20)}
    block["subject"] = "MK" + GAP * SPLIT + "WWWWWWW"  # 7 of 9 residues, well over 10%
    _kept, _trimmed, gapped, _columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    assert gapped == {}


def test_a_cluster_near_its_own_body_is_never_a_candidate() -> None:
    """An ordinary insertion is not a fling however badly it agrees, because a gate that fired on
    disagreement alone would just be deleting divergent sequence."""
    block = {f"crowd{index}": BODY + GAP * 5 + "ACDEFGH" for index in range(20)}
    block["subject"] = BODY + GAP * 5 + "WWWWWWW"
    _kept, _trimmed, gapped, _columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    assert gapped == {}


def test_leading_and_trailing_gaps_do_not_split_a_row() -> None:
    """A row's flanking gaps are where the row is not, not a hole inside it. Treating them as
    separators would make one contiguous fragment look like a fling of itself."""
    assert codon._residue_clusters(GAP * 500 + "MKLVDE" + GAP * 500, SPLIT) is None
    assert codon._residue_clusters("MKLVDE", SPLIT) is None
    assert codon._residue_clusters(GAP * 500, SPLIT) is None


def test_a_row_split_into_two_clusters_is_found() -> None:
    clusters = codon._residue_clusters("MK" + GAP * SPLIT + "LV", SPLIT)
    assert clusters == [[0, 1], [SPLIT + 2, SPLIT + 3]]


def test_a_column_left_empty_by_gapping_goes_with_it() -> None:
    """The column existed only to hold residues this filter just removed, so the shipped width must
    not keep paying for it — the same argument `drop_exemplar_only_columns` makes, and one
    `drop_unsequenced_codon_columns` deliberately will not make, since to it an unoccupied column is
    not an unsequenced one."""
    block = {f"crowd{index}": BODY + GAP * SPLIT + "ACDEFGH" + GAP for index in range(20)}
    block["subject"] = BODY + GAP * SPLIT + "WWWWWWW" + "W"
    width = len(block["subject"])
    kept, _trimmed, gapped, columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    assert gapped == {"subject": 8}
    assert columns == 1
    assert all(len(row) == width - 1 for row in kept.values())


def test_the_gapped_block_still_backtranslates() -> None:
    """The whole point of cutting `orf_nt` in step. `backtranslate` refuses a row whose non-gap
    residues do not number its codons exactly, so this passing is the invariant holding."""
    block = flung_block("WWWWWWW")
    kept, trimmed, _gapped, _columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    width_aa = len(next(iter(kept.values())))
    aligned = codon.backtranslate(kept, trimmed, width_aa)
    assert all(len(row) == 3 * width_aa for row in aligned.values())
    assert aligned["subject"].endswith("---" * 7)


def test_a_cluster_alone_in_every_column_it_occupies_is_gapped() -> None:
    """There is nothing there to agree with, and the reason it is being examined is that it sits
    hundreds of columns from its own row. Scoring it 1.000 for being unopposed would let a row be
    spared by the very error that put it there."""
    block = {f"crowd{index}": BODY + GAP * SPLIT + GAP * 7 for index in range(20)}
    block["subject"] = BODY + GAP * SPLIT + "WWWWWWW"
    _kept, _trimmed, gapped, columns = codon.gap_flung_clusters(
        block, orfs_for(block), contract.CodonSpec()
    )
    assert gapped == {"subject": 7}
    assert columns == 7
