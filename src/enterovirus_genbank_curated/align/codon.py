"""The codon-aware CDS block: MAFFT builds a backbone from full-length exemplars, the rest of the
backbone tier joins with `--add`, the addon tier joins as fragments with `--addfragments` under a
steeper local gap-open, and the resulting gapped amino-acid alignment is backtranslated onto each
record's own unaligned nucleotide ORF.

Ported from the upstream `build_{ev,polio,grand_ev}_cds_codon_msa.py` — structurally identical
across all three upstream scripts, so this repo needs one implementation rather than three; a
population plus its `CodonSpec` already carries everything that varied between them.

## Where this diverges from upstream

- **Seed tie-breaking is `(-length, accession)`, not `-length` alone.** Upstream's
  `sorted(al, key=lambda a: -len(aa[a]))[:SEED_PER_TYPE]` leaves a length tie to Python's stable
  sort over whatever order the accessions happened to be appended in — itself just ORF-AA FASTA
  file order, deterministic today by accident rather than by declared rule. An explicit accession
  secondary key makes the same outcome hold regardless of iteration order.
- **The backtranslation invariant is checked exactly**, not `nongap == len(nt) // 3` (upstream's
  actual check, which floor-divides and so would not catch `len(nt)` off by one or two nt if that
  still happened to floor-divide to the right integer). `align.segment`'s trailing-partial-codon
  rule already guarantees every `orf_nt` is a whole number of codons, so `nongap * 3 == len(nt)`
  should always hold by construction — checking it exactly turns a silent near-miss into a loud one.
- Seed grouping uses `type_sort_key` (the same blank-type sentinel `align.population` already
  established for row ordering), not the raw `virus_type` string, so a blank-typed record that
  somehow qualified for seeding would group with its sentinel rather than under an empty string.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterovirus_genbank_curated.align import contract, fasta
from enterovirus_genbank_curated.align.population import AlignmentPopulation
from enterovirus_genbank_curated.align.runner import ToolResult, run_tool
from enterovirus_genbank_curated.align.scratch import Scratch
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.align.toolchain import Toolchain
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.sandbox_exec import ToolGuard

SEED_FASTA = "cds_seed.fa"
SEED_ALIGNED_FASTA = "cds_seed_aln.fa"
BACKBONE_REST_FASTA = "cds_backbone_rest.fa"
PASS1_ALIGNED_FASTA = "cds_pass1_aln.fa"
ADDON_FASTA = "cds_addon.fa"
PASS2_ALIGNED_FASTA = "cds_pass2_aln.fa"

GAP = "-"
CODON_GAP = "---"


@dataclass(frozen=True)
class CodonAlignment:
    width_aa: int
    width_nt: int
    aligned_nt: dict[str, str]
    seed: tuple[str, ...]
    backbone_rest: tuple[str, ...]
    addon: tuple[str, ...]
    execs: tuple[ToolResult, ...]


def _aa_by_tier(
    population: AlignmentPopulation, segmentations: dict[str, Segmentation]
) -> tuple[dict[str, str], dict[str, str]]:
    """{accession: aa}, split by tier, over records with placeable AA content. A record whose
    segmentation `method` is `"none"` has nothing to align and is not this module's concern —
    `align.stitch` pads it as an all-gap row later."""
    backbone: dict[str, str] = {}
    addon: dict[str, str] = {}
    for record in population.records:
        segmentation = segmentations[record.accession]
        if segmentation.method == "none":
            continue
        target = backbone if record.tier == "backbone" else addon
        target[record.accession] = segmentation.aa
    return backbone, addon


def choose_seed(
    population: AlignmentPopulation, backbone_aa: dict[str, str], spec: contract.CodonSpec
) -> tuple[str, ...]:
    """Up to `seed_per_type` of the longest backbone-tier exemplars per type, `seed_min_aa` aa or
    longer. Ties break on accession — see the module docstring."""
    by_type: dict[str, list[str]] = {}
    for record in population.records:
        aa = backbone_aa.get(record.accession)
        if aa is None or len(aa) < spec.seed_min_aa:
            continue
        by_type.setdefault(record.type_sort_key, []).append(record.accession)

    seed: list[str] = []
    for accessions in by_type.values():
        ranked = sorted(accessions, key=lambda acc: (-len(backbone_aa[acc]), acc))
        seed.extend(ranked[: spec.seed_per_type])
    return tuple(sorted(seed))


def backtranslate(aa_aln: dict[str, str], orf_nt: dict[str, str], width_aa: int) -> dict[str, str]:
    """Map each gapped amino-acid row back onto its record's own unaligned nucleotide ORF: a gap
    becomes `"---"`, a residue becomes the next untouched codon, walking a running codon index
    that only advances on non-gap characters. See the module docstring for the invariant this
    rests on and how strictly it is checked here.
    """
    aligned_nt: dict[str, str] = {}
    for accession, row in aa_aln.items():
        nt = orf_nt[accession]
        nongap = len(row) - row.count(GAP)
        if nongap * 3 != len(nt):
            raise ContractError(
                f"{accession}: {nongap} aligned non-gap residues but {len(nt)} nt of ORF "
                f"(not {nongap} whole codons); the AA<->codon invariant broke"
            )
        pieces: list[str] = []
        codon_index = 0
        for character in row:
            if character == GAP:
                pieces.append(CODON_GAP)
            else:
                pieces.append(nt[codon_index * 3 : codon_index * 3 + 3])
                codon_index += 1
        joined = "".join(pieces)
        if len(joined) != 3 * width_aa:
            raise ContractError(
                f"{accession}: backtranslated width {len(joined)} != {3 * width_aa}"
            )
        aligned_nt[accession] = joined
    return aligned_nt


# A codon column every occupant spells with ambiguity carries no homology signal — nobody's base is
# known there, so nothing can be aligned to anything. `mafft --addfragments` opens such columns
# faithfully, because an N-run *is* an insertion as far as the aligner can tell, and the result was
# 7,130 all-N columns in `NPEV_unified` — 48.8% of its CDS block — held open by eleven deposits with
# assembly gaps padded to full length. `PX242045` alone opened 2,169.
#
# Measured before this was written: 2.4.1's NPEV CDS carried the *same* 43,110 N residues in 7,677
# columns with **zero** all-N columns. So this is not a cost of the `--lop` placement fix, which is
# what an earlier reading of the width claimed; the non-N part of the block is 209 columns narrower
# than 2.4.1's. The padding is the whole difference.
#
# Dropped at codon granularity because `backtranslate` emits `"---"` or a whole codon, so removing a
# single column would break the reading frame and the whole-codon width invariant with it. The
# filter discards **no** unambiguous nucleotide: over both affected artifacts it removes 35,931
# residues and every one is an ambiguity code. N's that MAFFT placed on shared columns stay — those
# are informative, meaning "unsequenced at this homologous position", which is a different statement
# from a deletion and one the p-distance readers already handle.
AMBIGUOUS_CODON = frozenset("Nn-.")


def drop_unsequenced_codon_columns(
    aligned_nt: dict[str, str], width_aa: int
) -> tuple[dict[str, str], int]:
    """Remove codon columns no record spells with a known base. Returns the rows and how many went.

    A column with no occupant at all is left alone: that is an ordinary gap column, and dropping it
    would silently change the meaning of this function from "unsequenced" to "unused".
    """
    doomed: list[int] = []
    for codon in range(width_aa):
        start = 3 * codon
        occupied = False
        informative = False
        for row in aligned_nt.values():
            triplet = row[start : start + 3]
            if triplet == "---":
                continue
            occupied = True
            if any(base not in AMBIGUOUS_CODON for base in triplet):
                informative = True
                break
        if occupied and not informative:
            doomed.append(codon)
    if not doomed:
        return aligned_nt, 0

    cut = set(doomed)
    kept = {
        accession: "".join(
            row[3 * codon : 3 * codon + 3] for codon in range(width_aa) if codon not in cut
        )
        for accession, row in aligned_nt.items()
    }
    # A row emptied by this filter would be `present` and all-gap, which `validation/alignment.py`
    # fails outright. No row is emptied today — every affected record keeps thousands of real
    # bases — and if one ever would be, that is a record whose CDS is *entirely* unsequenced and
    # the honest response is to stop rather than to ship a blank row.
    # `not row` matters as much as the all-gap case: a row whose every column is dropped becomes
    # the empty string, which a truthiness guard would skip straight past.
    emptied = sorted(a for a, row in kept.items() if not row or set(row) <= set("-."))
    if emptied:
        raise ContractError(
            f"dropping unsequenced codon columns would empty {len(emptied)} row(s) "
            f"({emptied[:5]}); those records carry no sequenced CDS at all and must not ship "
            f"as blank rows"
        )
    return kept, len(doomed)


def build_codon_block(
    population: AlignmentPopulation,
    segmentations: dict[str, Segmentation],
    toolchain: Toolchain,
    scratch: Scratch,
    guard: ToolGuard,
    *,
    threads: int,
    timeout_s: int,
    step_offset: int = 0,
) -> CodonAlignment:
    """Seed, add the rest of the backbone, add the addon fragments, backtranslate. Three MAFFT
    calls at most — fewer if the backbone-rest or addon tier is empty for this population."""
    spec = population.spec.codon
    backbone_aa, addon_aa = _aa_by_tier(population, segmentations)

    seed = choose_seed(population, backbone_aa, spec)
    if not seed:
        raise ContractError(
            f"{population.spec.name}: no backbone record reaches seed_min_aa="
            f"{spec.seed_min_aa} aa; the codon block has no exemplar to seed a backbone from"
        )
    seed_set = set(seed)
    backbone_rest = tuple(sorted(acc for acc in backbone_aa if acc not in seed_set))
    addon = tuple(sorted(addon_aa))

    execs: list[ToolResult] = []
    name = population.spec.name

    fasta.write_fasta({acc: backbone_aa[acc] for acc in seed}, scratch.root / SEED_FASTA)
    seed_result = run_tool(
        toolchain,
        "mafft-linsi",
        ["--anysymbol", "--thread", str(threads), SEED_FASTA],
        scratch=scratch,
        index=step_offset,
        label=f"{name}_cds_seed",
        inputs={SEED_FASTA: scratch.root / SEED_FASTA},
        outputs=[],
        stdout_to=SEED_ALIGNED_FASTA,
        threads=threads,
        timeout_s=timeout_s,
        guard=guard,
    )
    execs.append(seed_result)
    assert seed_result.stdout_path is not None
    onto_basename, onto_path = SEED_ALIGNED_FASTA, seed_result.stdout_path

    if backbone_rest:
        fasta.write_fasta(
            {acc: backbone_aa[acc] for acc in backbone_rest}, scratch.root / BACKBONE_REST_FASTA
        )
        pass1_result = run_tool(
            toolchain,
            "mafft",
            [
                "--thread", str(threads), "--anysymbol", "--op", str(spec.pass1_gap_open),
                "--ep", str(spec.gap_extend),
                "--add", BACKBONE_REST_FASTA, onto_basename,
            ],
            scratch=scratch,
            index=step_offset + 1,
            label=f"{name}_cds_pass1",
            inputs={
                BACKBONE_REST_FASTA: scratch.root / BACKBONE_REST_FASTA,
                onto_basename: onto_path,
            },
            outputs=[],
            stdout_to=PASS1_ALIGNED_FASTA,
            threads=threads,
            timeout_s=timeout_s,
            guard=guard,
        )
        execs.append(pass1_result)
        assert pass1_result.stdout_path is not None
        onto_basename, onto_path = PASS1_ALIGNED_FASTA, pass1_result.stdout_path

    if addon:
        fasta.write_fasta({acc: addon_aa[acc] for acc in addon}, scratch.root / ADDON_FASTA)
        pass2_result = run_tool(
            toolchain,
            "mafft",
            [
                "--thread", str(threads), "--anysymbol", "--op", str(spec.pass2_gap_open),
                "--ep", str(spec.gap_extend),
                "--lop", str(spec.pass2_local_gap_open), "--addfragments", ADDON_FASTA,
                onto_basename,
            ],
            scratch=scratch,
            index=step_offset + 2,
            label=f"{name}_cds_pass2",
            inputs={ADDON_FASTA: scratch.root / ADDON_FASTA, onto_basename: onto_path},
            outputs=[],
            stdout_to=PASS2_ALIGNED_FASTA,
            threads=threads,
            timeout_s=timeout_s,
            guard=guard,
        )
        execs.append(pass2_result)
        assert pass2_result.stdout_path is not None
        onto_path = pass2_result.stdout_path

    aa_aln = fasta.read_fasta(onto_path)

    expected = seed_set | set(backbone_rest) | set(addon)
    missing = expected - set(aa_aln)
    if missing:
        raise ContractError(
            f"{name}: {len(missing)} record(s) absent from the codon AA alignment: "
            f"{sorted(missing)[:10]}"
        )
    extra = set(aa_aln) - expected
    if extra:
        raise ContractError(
            f"{name}: {len(extra)} unexpected record(s) in the codon AA alignment: "
            f"{sorted(extra)[:10]}"
        )

    widths = {len(row) for row in aa_aln.values()}
    if len(widths) != 1:
        raise ContractError(
            f"{name}: codon AA alignment is not rectangular: widths={sorted(widths)}"
        )
    width_aa = widths.pop()

    orf_nt = {acc: segmentations[acc].orf_nt for acc in expected}
    aligned_nt = backtranslate(aa_aln, orf_nt, width_aa)
    aligned_nt, dropped_codons = drop_unsequenced_codon_columns(aligned_nt, width_aa)
    width_aa -= dropped_codons

    return CodonAlignment(
        width_aa=width_aa,
        width_nt=3 * width_aa,
        aligned_nt=aligned_nt,
        seed=seed,
        backbone_rest=backbone_rest,
        addon=addon,
        execs=tuple(execs),
    )
