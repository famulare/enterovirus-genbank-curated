"""The NCR (non-coding region) block: `cmalign` against an already-committed covariance model.
Infernal's own consensus/match-column marking (`#=GC RF`, non-gap) is what fixes the alignment's
columns — insert-column residues are discarded, not kept as extra, ragged columns.

Ported from MAD-VDPV's `build_{ev,polio,grand_ev}_ncr_structural.py`, but only the `cmalign` step:
the CM itself is a committed input-of-record (`registry/alignment_seeds/`, verified cheaply by
`align.seeds`), not rebuilt here — the `mafft-xinsi`/`RNAalifold`/`cmbuild` seed-and-build path
those scripts also contain is a separate, gated, not-expected-to-run prerequisite.

Only records whose segmentation succeeded via the `"annotated"` method carry NCR content at all —
`align.segment`'s inferred-ORF fallback has no NCR at all ("boundaries not trustworthy", its own
module docstring). Those records, and any annotated record whose NCR fragment falls outside the
declared population window (see `contract.NcrSideSpec`), get no block here; `align.stitch` pads
them with an all-gap block of the same width, exactly as upstream's own stitch step does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Bio import AlignIO

from enterovirus_genbank_curated.align import contract, fasta
from enterovirus_genbank_curated.align.population import AlignmentPopulation
from enterovirus_genbank_curated.align.runner import ToolResult, run_tool
from enterovirus_genbank_curated.align.scratch import Scratch
from enterovirus_genbank_curated.align.segment import Segmentation
from enterovirus_genbank_curated.align.toolchain import Toolchain
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.sandbox_exec import ToolGuard

SIDES = ("5p", "3p")
POP_FASTA = {"5p": "ncr_5p_pop.fa", "3p": "ncr_3p_pop.fa"}
CMALIGN_STOCKHOLM = {"5p": "ncr_5p_cmalign.sto", "3p": "ncr_3p_cmalign.sto"}

# Infernal's convention: a `#=GC RF` character is a consensus/match column unless it is one of
# these gap symbols, in which case the column is an insert column and is dropped.
NOT_MATCH_COLUMN = frozenset({".", "-", "~"})
GAP_SYMBOL = "-"

# The closed vocabulary for what happens to one record's NCR fragment against a side's population
# window — shared by the cmalign population filter below and align.stitch's coverage sidecar, so
# the two can never classify the same fragment differently.
FRAGMENT_INCLUDED = "included"
FRAGMENT_EMPTY = "empty_fragment"
FRAGMENT_BELOW_POP_MIN = "below_pop_min"
FRAGMENT_EXCLUDED_OVERSIZED = "excluded_oversized"


def classify_fragment(fragment: str, spec: contract.NcrSideSpec) -> str:
    """Which of the four fates one NCR fragment meets against a side's population window. The
    single place this predicate is expressed — see the module-level vocabulary comment above."""
    if not fragment:
        return FRAGMENT_EMPTY
    length = len(fragment)
    if length < spec.pop_min_nt:
        return FRAGMENT_BELOW_POP_MIN
    if spec.pop_max_nt is not None and length > spec.pop_max_nt:
        return FRAGMENT_EXCLUDED_OVERSIZED
    return FRAGMENT_INCLUDED


@dataclass(frozen=True)
class NcrBlock:
    side: str
    width_nt: int
    aligned_nt: dict[str, str]
    ss_cons: str
    excluded_oversized: tuple[str, ...]
    exec_result: ToolResult


def _ncr_population(
    segmentations: dict[str, Segmentation],
    accessions: frozenset[str],
    side: str,
    spec: contract.NcrSideSpec,
) -> tuple[dict[str, str], tuple[str, ...]]:
    """{accession: ncr sequence}, over annotated records in `accessions` whose fragment on this
    side is non-empty and within `[pop_min_nt, pop_max_nt]`. Also returns the accessions excluded
    for being oversized — see `NcrSideSpec`'s docstring for what that means."""
    population: dict[str, str] = {}
    excluded: list[str] = []
    for accession in accessions:
        segmentation = segmentations[accession]
        if segmentation.method != "annotated":
            continue
        sequence = segmentation.ncr5 if side == "5p" else segmentation.ncr3
        classification = classify_fragment(sequence, spec)
        if classification == FRAGMENT_INCLUDED:
            population[accession] = sequence
        elif classification == FRAGMENT_EXCLUDED_OVERSIZED:
            excluded.append(accession)
    return population, tuple(sorted(excluded))


def _match_columns(sto_path: Path) -> tuple[dict[str, str], str]:
    """Keep only cmalign's consensus (match) columns, ported verbatim from upstream's
    `match_columns()`. See the module-level `NOT_MATCH_COLUMN` comment for the rule."""
    alignment = AlignIO.read(sto_path, "stockholm")
    rf = alignment.column_annotations["reference_annotation"]
    ss = alignment.column_annotations.get("secondary_structure", "." * len(rf))
    keep = [i for i, c in enumerate(rf) if c not in NOT_MATCH_COLUMN]
    rows = {
        record.id: "".join(str(record.seq)[i] for i in keep).upper().replace(".", GAP_SYMBOL)
        for record in alignment
    }
    ss_kept = "".join(ss[i] for i in keep)
    return rows, ss_kept


def build_ncr_block(
    population: AlignmentPopulation,
    side: str,
    segmentations: dict[str, Segmentation],
    side_spec: contract.NcrSideSpec,
    toolchain: Toolchain,
    scratch: Scratch,
    guard: ToolGuard,
    repository_root: Path,
    *,
    threads: int,
    timeout_s: int,
    index: int,
) -> NcrBlock:
    if side not in SIDES:
        raise ContractError(f"side must be one of {SIDES}, got {side!r}")

    accessions = frozenset(record.accession for record in population.records)
    ncr_population, excluded = _ncr_population(segmentations, accessions, side, side_spec)
    if not ncr_population:
        raise ContractError(
            f"{population.spec.name} {side}: no record in the declared population window "
            f"[{side_spec.pop_min_nt}, {side_spec.pop_max_nt}] has an annotated NCR fragment"
        )

    pop_fasta_name = POP_FASTA[side]
    fasta.write_fasta(ncr_population, scratch.root / pop_fasta_name)

    cm_path = repository_root / side_spec.cm_path
    cmalign_output_name = CMALIGN_STOCKHOLM[side]
    result = run_tool(
        toolchain,
        "cmalign",
        ["--outformat", "Stockholm", "-o", cmalign_output_name, cm_path.name, pop_fasta_name],
        scratch=scratch,
        index=index,
        label=f"{population.spec.name}_ncr_{side}",
        inputs={pop_fasta_name: scratch.root / pop_fasta_name, cm_path.name: cm_path},
        outputs=[cmalign_output_name],
        threads=threads,
        timeout_s=timeout_s,
        guard=guard,
    )

    rows, ss_cons = _match_columns(result.run_dir / cmalign_output_name)

    missing = set(ncr_population) - set(rows)
    if missing:
        raise ContractError(
            f"{population.spec.name} {side}: {len(missing)} record(s) absent from the cmalign "
            f"output: {sorted(missing)[:10]}"
        )

    widths = {len(row) for row in rows.values()}
    if len(widths) != 1:
        raise ContractError(
            f"{population.spec.name} {side}: match-column block is not rectangular: "
            f"widths={sorted(widths)}"
        )
    width = widths.pop()

    return NcrBlock(
        side=side,
        width_nt=width,
        aligned_nt=rows,
        ss_cons=ss_cons,
        excluded_oversized=excluded,
        exec_result=result,
    )


def build_ncr_blocks(
    population: AlignmentPopulation,
    segmentations: dict[str, Segmentation],
    toolchain: Toolchain,
    scratch: Scratch,
    guard: ToolGuard,
    repository_root: Path,
    *,
    threads: int,
    timeout_s: int,
    step_offset: int = 0,
) -> tuple[NcrBlock, NcrBlock]:
    """(5' block, 3' block), for a population whose spec declares an `NcrSpec`."""
    ncr_spec = population.spec.ncr
    if ncr_spec is None:
        raise ContractError(f"{population.spec.name} has no declared NcrSpec")
    five = build_ncr_block(
        population, "5p", segmentations, ncr_spec.five_prime, toolchain, scratch, guard,
        repository_root, threads=threads, timeout_s=timeout_s, index=step_offset,
    )
    three = build_ncr_block(
        population, "3p", segmentations, ncr_spec.three_prime, toolchain, scratch, guard,
        repository_root, threads=threads, timeout_s=timeout_s, index=step_offset + 1,
    )
    return five, three
