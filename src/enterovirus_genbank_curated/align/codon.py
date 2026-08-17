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
- **The seed additionally carries clade exemplars from outside the carve.** `choose_seed` can only
  reach records this corpus holds, and this corpus holds no Rhinovirus A or B polyprotein at all —
  the longest RV-A ORF here is 142 aa against a `seed_min_aa` of 2,000. See `align.exemplars` for
  what that cost the shipped file and why adding four RefSeq polyproteins to the seed, and removing
  them again before backtranslation, is the smallest thing that fixes it.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from enterovirus_genbank_curated.align import contract, exemplars, fasta
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
    clade_exemplars: tuple[str, ...] = ()
    exemplar_only_codons_dropped: int = 0
    unsequenced_codons_dropped: int = 0
    # {accession: codons removed} for rows that had a flung cluster gapped, and the columns that
    # emptied when those clusters went. Per record rather than as a total, because eighteen rows is
    # few enough to name, and a reader who cannot see which rows lost residues cannot check it.
    flung_codons_gapped: dict[str, int] = field(default_factory=dict)
    flung_only_columns_dropped: int = 0


def _aa_by_tier(
    population: AlignmentPopulation, segmentations: dict[str, Segmentation]
) -> tuple[dict[str, str], dict[str, str]]:
    """{accession: aa}, split by tier, over records with placeable AA content. A record whose
    segmentation `method` is `"noncoding"` or `"none"` has no protein to align and is not this
    module's concern — `align.stitch` pads it as an all-gap CDS span, and for `noncoding`
    `align.structural` offers its sequence to the 5'NCR block instead."""
    backbone: dict[str, str] = {}
    addon: dict[str, str] = {}
    for record in population.records:
        segmentation = segmentations[record.accession]
        if segmentation.method in ("noncoding", "none"):
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


def drop_exemplar_only_columns(
    aa_aln: dict[str, str], exemplar_rows: frozenset[str]
) -> tuple[dict[str, str], int]:
    """Remove the exemplar rows, then every column no surviving row occupies. Returns both.

    Deliberately *not* folded into `drop_unsequenced_codon_columns`, which leaves an unoccupied
    column alone on the stated grounds that dropping it would change that function's meaning from
    "unsequenced" to "unused". Both meanings are wanted; they are two functions. This one runs on
    the amino-acid alignment, before backtranslation, where one column is one codon and the
    whole-codon width invariant cannot be broken by construction.
    """
    kept = {name: row for name, row in aa_aln.items() if name not in exemplar_rows}
    if not kept:
        raise ContractError(
            "every row in the codon amino-acid alignment is a clade exemplar; the population "
            "contributed nothing"
        )
    widths = {len(row) for row in kept.values()}
    if len(widths) != 1:
        raise ContractError(f"codon AA alignment is not rectangular: widths={sorted(widths)}")
    width = widths.pop()
    occupied = [any(row[column] != GAP for row in kept.values()) for column in range(width)]
    dropped = width - sum(occupied)
    if not dropped:
        return kept, 0
    trimmed = {
        name: "".join(row[column] for column in range(width) if occupied[column])
        for name, row in kept.items()
    }
    return trimmed, dropped


_COLUMN_CHUNK = 128


def _column_residue_counts(
    rows: list[str], wanted: set[int], width: int
) -> dict[int, Counter[str]]:
    """Residue counts for the requested columns only, by transposing in chunks.

    A column is only reachable by indexing every row at it, and doing that one column at a time over
    a 24,000-row alignment is tens of millions of interpreted operations. Slicing a chunk of columns
    out of every row and handing the chunk to `zip` moves the transpose into C, and chunks with no
    requested column are skipped entirely — so the cost tracks the handful of columns some cluster
    actually lands in, not the width of the block.
    """
    counts: dict[int, Counter[str]] = {}
    for start in range(0, width, _COLUMN_CHUNK):
        stop = min(start + _COLUMN_CHUNK, width)
        if not any(column in wanted for column in range(start, stop)):
            continue
        block = [row[start:stop] for row in rows]
        for column, letters in zip(range(start, stop), zip(*block, strict=True), strict=True):
            if column in wanted:
                counts[column] = Counter(letters)
    return counts


def _residue_clusters(row: str, split: int) -> list[list[int]] | None:
    """This row's placed columns grouped into clusters, or None if it has only one cluster.

    Clusters are separated by a run of at least `split` gaps. Leading and trailing gaps are not
    separators — they are where the row is not, not a hole inside it — so the search is over the
    interior only. That interior test is a substring search and so is free, which is what keeps this
    from having to enumerate the gap pattern of every row in the block.
    """
    first = len(row) - len(row.lstrip(GAP))
    trimmed = row.rstrip(GAP)
    if not trimmed:
        return None
    if GAP * split not in trimmed[first:]:
        return None
    clusters: list[list[int]] = []
    current: list[int] = []
    run = 0
    for column in range(first, len(trimmed)):
        if row[column] == GAP:
            run += 1
            continue
        if run >= split and current:
            clusters.append(current)
            current = []
        run = 0
        current.append(column)
    if current:
        clusters.append(current)
    return clusters if len(clusters) > 1 else None


def gap_flung_clusters(
    aa_aln: dict[str, str], orf_nt: dict[str, str], spec: contract.CodonSpec
) -> tuple[dict[str, str], dict[str, str], dict[str, int], int]:
    """Remove clusters of residues MAFFT parked far from their row with nothing homologous there.

    Returns the amino-acid alignment, the ORFs with the removed codons taken out of them, the count
    removed per record, and how many columns went empty as a result and were dropped.

    See `CodonSpec.fling_min_identity` for the measurement: 34 clusters score 0.000-0.333 against
    the consensus of the columns they land in and 9 score 0.667-0.955, and the nine are genuine
    bipartite fragments whose halves each sit on real homology. Being far from the rest of the row
    is what makes a cluster worth examining; disagreeing with what is there is what condemns it.

    The row's own residue is subtracted from each column's counts before the majority is taken. In a
    column with thousands of occupants that changes nothing, but a cluster can land somewhere nearly
    empty, and there a row voting for itself would score 1.000 and be spared by its own error.

    `orf_nt` is cut in step with the alignment because `backtranslate` rests on the row's non-gap
    residues numbering exactly its codons. Cutting the two together is what keeps that invariant an
    invariant rather than something this function has to be trusted not to break.
    """
    accessions = sorted(aa_aln)
    rows = [aa_aln[accession] for accession in accessions]
    width = len(rows[0])

    proposed: list[tuple[str, list[int]]] = []
    for accession, row in zip(accessions, rows, strict=True):
        clusters = _residue_clusters(row, spec.fling_split_codons)
        if clusters is None:
            continue
        placed = sum(len(cluster) for cluster in clusters)
        body = max(range(len(clusters)), key=lambda index: len(clusters[index]))
        for index, cluster in enumerate(clusters):
            if index == body:
                continue
            if len(cluster) / placed <= spec.fling_max_share:
                proposed.append((accession, cluster))
    if not proposed:
        return aa_aln, orf_nt, {}, 0

    wanted = {column for _accession, cluster in proposed for column in cluster}
    counts = _column_residue_counts(rows, wanted, width)

    condemned: dict[str, set[int]] = {}
    for accession, cluster in proposed:
        row = aa_aln[accession]
        agree = compared = 0
        for column in cluster:
            others = counts[column] - Counter(row[column])
            others.pop(GAP, None)
            if not others:
                continue  # nothing there to agree or disagree with
            compared += 1
            agree += row[column] == others.most_common(1)[0][0]
        # A cluster alone in every column it occupies has no homology to appeal to, and the whole
        # reason it is being examined is that it sits hundreds of columns from its own row.
        identity = agree / compared if compared else 0.0
        if identity < spec.fling_min_identity:
            condemned.setdefault(accession, set()).update(cluster)
    if not condemned:
        return aa_aln, orf_nt, {}, 0

    gapped_aa: dict[str, str] = dict(aa_aln)
    trimmed_nt: dict[str, str] = dict(orf_nt)
    removed: dict[str, int] = {}
    for accession, columns in condemned.items():
        row = aa_aln[accession]
        # Which of this row's own codons the condemned columns are, in ORF order.
        doomed_codons = set()
        codon_index = 0
        for column, character in enumerate(row):
            if character == GAP:
                continue
            if column in columns:
                doomed_codons.add(codon_index)
            codon_index += 1
        gapped_aa[accession] = "".join(
            GAP if column in columns else character for column, character in enumerate(row)
        )
        nt = orf_nt[accession]
        trimmed_nt[accession] = "".join(
            nt[index * 3 : index * 3 + 3]
            for index in range(len(nt) // 3)
            if index not in doomed_codons
        )
        removed[accession] = len(doomed_codons)
        if not trimmed_nt[accession]:
            raise ContractError(
                f"{accession}: gapping flung clusters would remove its whole ORF; a cluster capped "
                f"at fling_max_share={spec.fling_max_share} cannot be the whole row, so the "
                f"cluster arithmetic is wrong rather than the record being unusual"
            )

    # A column that existed only to hold a cluster we just removed is a column the shipped width
    # should not pay for — the same argument `drop_exemplar_only_columns` makes, and the same reason
    # `drop_unsequenced_codon_columns` cannot be left to do it: to that filter an unoccupied column
    # is not an unsequenced one, and it deliberately leaves it alone.
    emptied = sorted(
        column
        for column in wanted
        if all(gapped_aa[accession][column] == GAP for accession in accessions)
    )
    if emptied:
        cut = set(emptied)
        gapped_aa = {
            accession: "".join(
                character for column, character in enumerate(row) if column not in cut
            )
            for accession, row in gapped_aa.items()
        }
    return gapped_aa, trimmed_nt, removed, len(emptied)


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
# Measured on the diagnostic run that motivated this filter: 2.4.1's NPEV CDS carried the *same*
# 43,110 N residues in 7,677 columns with **zero** all-N columns. So the width was not a cost of the
# `--lop` placement fix, which is what an earlier reading of it claimed. The padding is the whole
# difference.
#
# Dropped at codon granularity because `backtranslate` emits `"---"` or a whole codon, so removing a
# single column would break the reading frame and the whole-codon width invariant with it. That is
# also why the shipped `NPEV_unified` still has 9 gap-or-N columns: an ambiguous nucleotide whose
# two codon partners carry real bases is not droppable, and dropping it would be wrong.
#
# The filter discards **no** unambiguous nucleotide, and that is a property of the predicate rather
# than a measurement to re-take: a column only goes if *every* row spells it from `AMBIGUOUS_CODON`.
# `tests/test_align_codon.py` pins it constructively. On the shipped bytes NPEV's CDS goes 14,598 ->
# 7,503 columns and 43,110 -> 25,155 N residues, with POLIO and every PV{n} file unchanged — their
# blocks had no all-ambiguous codon to drop. N's that MAFFT placed on shared columns stay: those are
# informative, meaning "unsequenced at this homologous position", which is a different statement
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
    repository_root: Path,
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

    clade_exemplars = exemplars.load_clade_exemplars(repository_root)
    exemplars.assert_disjoint_from(
        clade_exemplars, frozenset(record.accession for record in population.records)
    )
    exemplar_rows = {exemplar.row_name: exemplar.aa for exemplar in clade_exemplars}

    execs: list[ToolResult] = []
    name = population.spec.name

    fasta.write_fasta(
        {**{acc: backbone_aa[acc] for acc in seed}, **exemplar_rows}, scratch.root / SEED_FASTA
    )
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
    missing = (expected | set(exemplar_rows)) - set(aa_aln)
    if missing:
        raise ContractError(
            f"{name}: {len(missing)} record(s) absent from the codon AA alignment: "
            f"{sorted(missing)[:10]}"
        )
    extra = set(aa_aln) - expected - set(exemplar_rows)
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

    aa_aln, exemplar_only_codons = drop_exemplar_only_columns(aa_aln, frozenset(exemplar_rows))

    orf_nt = {acc: segmentations[acc].orf_nt for acc in expected}
    # After the exemplars are gone, so the seed-only rows never vote on a column's consensus, and
    # before backtranslation, because the claim being tested is about residues and homology.
    aa_aln, orf_nt, flung, flung_columns = gap_flung_clusters(aa_aln, orf_nt, spec)
    width_aa = len(next(iter(aa_aln.values())))

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
        clade_exemplars=tuple(exemplar.exemplar_id for exemplar in clade_exemplars),
        exemplar_only_codons_dropped=exemplar_only_codons,
        unsequenced_codons_dropped=dropped_codons,
        flung_codons_gapped=dict(sorted(flung.items())),
        flung_only_columns_dropped=flung_columns,
    )
