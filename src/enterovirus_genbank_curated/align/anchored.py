"""The Sabin-anchored CDS block: a pairwise reference-frame projection, no MAFFT at all.

Ported from MAD-VDPV's `codon_align.py` (the TAB engine), `build_reference_alignments.py` (BS0a, the
nucleotide anchor) and `build_reference_msa.py` (BS0b, the projection). Where the unified stack
builds one profile alignment over a whole population, this aligns each record independently against
one Sabin reference and writes it onto that reference's own coordinate frame. Two consequences worth
stating plainly, because they are the whole reason the second stack exists:

- **Every column is a real Sabin genome position.** Nothing is a consensus. So `#=GC RF` is the
  Sabin sequence itself, and a column number is a genome coordinate a reader can look up.
- **Insertions relative to the reference are dropped.** A query base with no reference position has
  nowhere to go in a fixed reference frame. This is lossy by construction and reported as such; the
  unified stack is where insertions survive.

## TAB: translate, align, backtranslate

Indels inside a picornavirus polyprotein ORF are placed on codon boundaries by protein homology
rather than by nucleotide similarity, because a nucleotide aligner will happily open a 1 or 2 nt gap
that implies a frameshift no real virus carries. So: translate the reference CDS and the query CDS,
align the two proteins, then impose that protein alignment back onto the nucleotides three at a
time. The UTRs stay nucleotide-aligned — they are not coding and have no frame to respect.

## Two do-no-harm guards, and why both are needed

Codon-awareness is an improvement on average and a liability on short divergent fragments, where
protein homology is weak enough that the amino-acid aligner places residues worse than plain
nucleotide identity would. Hence:

- **The nucleotide guard** (`pdist_guard_increase_pp`): if codon-aware placement worsens CDS
  nucleotide p-distance by more than 2 percentage points, revert to the nucleotide anchor.
- **The amino-acid guard** (`aa_guard_increase_pp`): if a record's own GenBank frame is a clean,
  stop-free alignment but the reference-inferred frame gives a *dramatically* lower amino-acid
  p-distance, the annotation is a broken off-by-one `codon_start` and the inferred frame wins. The
  bar is 30 pp rather than the nucleotide guard's 2 because overriding a submitter's own annotation
  needs a genuine rescue, and a small gain on an already-divergent record is alignment noise.

A frameshift record (internal stop in its own annotated frame) takes neither path: it is split at
non-×3 indels, each segment re-phased independently, and each TAB'd.

## Where this port diverges from upstream

- **No serotype assignment.** Upstream's BS0a aligned every candidate to all three Sabins and took
  the closest capsid as the serotype. Here membership and serotype are canonical `virus_type` by
  curator decision, so each record is aligned to exactly one reference — its own. That removes two
  thirds of the pairwise work and the entire ranking, confidence and discordance apparatus.
- **Only CDS-span blocks are assembled.** Upstream projected the whole genome and then sliced the
  CDS span out, discarding its own UTR columns in favour of the cmalign blocks. Assembling only the
  blocks is provably the same output over that span — upstream clipped its UTR blocks at exactly the
  CDS bounds, so they never reached inside it — and skips work whose result was thrown away.
- **The frame comes from the outer CDS span**, as upstream's did. `align.segment` has richer
  per-part detail, but the TAB engine works in single contiguous oriented coordinates, so a
  multi-part join has no unambiguous single frame origin to offer it. 90 of 27,164 CDS features are
  multi-part.
- **`translation_length` is unavailable** in this repository's feature tables, so the annotated
  frame's end bound always falls back to the nucleotide anchor's own CDS extent — which is exactly
  what upstream did whenever that column was absent or zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from Bio import Align
from Bio.Align import substitution_matrices

from enterovirus_genbank_curated.align import regions, segment
from enterovirus_genbank_curated.align.population import AlignmentPopulation
from enterovirus_genbank_curated.contracts import ContractError

GAP = "-"
ACGT = frozenset("ACGT")

# BS0a's locked semi-global settings: free end gaps so a fragment pays nothing to sit inside the
# genome, expensive internal gaps so it does not shred itself to buy mismatches.
NT_MATCH_SCORE = 2.0
NT_MISMATCH_SCORE = -1.0
NT_OPEN_INTERNAL_GAP_SCORE = -50.0
NT_EXTEND_INTERNAL_GAP_SCORE = -10.0

PROTEIN_MATRIX = "BLOSUM62"
PROTEIN_OPEN_INTERNAL_GAP_SCORE = -11.0
PROTEIN_EXTEND_INTERNAL_GAP_SCORE = -1.0

FORWARD = "forward"
REVERSE_COMPLEMENT = "reverse_complement"

METHOD_CODON = "codon"
METHOD_CODON_REF_INFERRED = "codon_ref_inferred"
METHOD_RECOVERED = "recovered"
METHOD_NT_CDS_FALLBACK = "nt_cds_fallback"
METHOD_NT_FALLBACK = "nt_fallback"
METHOD_NT_BETTER = "nt_better"


@dataclass(frozen=True)
class BlockAlignment:
    """Gapless ascending half-open 0-based `(start, end)` block pairs, plus how they were derived.

    Deliberately not a Biopython `Alignment`: the blocks are assembled from several sources (a
    protein alignment, a nucleotide alignment, per-segment recoveries) and there is no single
    Biopython object that spans them.
    """

    ref_blocks: tuple[tuple[int, int], ...]
    query_blocks: tuple[tuple[int, int], ...]
    method: str
    internal_stop: bool
    recovered: bool | None


@dataclass(frozen=True)
class AnchoredRow:
    accession: str
    strand: str
    method: str
    internal_stop: bool
    recovered: bool | None
    cds_row: str
    # Non-×3 CDS deletions inside the covered span: a frameshift signal, and for a real poliovirus
    # a sequencing or annotation artefact rather than biology.
    n_cds_gap_non_multiple_of_three: int
    n_cds_gap_misphased: int


@dataclass(frozen=True)
class AnchoredCdsBlock:
    serotype: str
    reference_accession: str
    cds_start: int
    cds_end: int
    width_nt: int
    reference_row: str
    aligned_nt: dict[str, str]
    rows: tuple[AnchoredRow, ...]
    over_length_cap: tuple[str, ...]


def nucleotide_aligner() -> Align.PairwiseAligner:
    aligner = Align.PairwiseAligner(mode="global")
    aligner.match_score = NT_MATCH_SCORE
    aligner.mismatch_score = NT_MISMATCH_SCORE
    aligner.open_internal_gap_score = NT_OPEN_INTERNAL_GAP_SCORE
    aligner.extend_internal_gap_score = NT_EXTEND_INTERNAL_GAP_SCORE
    aligner.open_left_gap_score = 0.0
    aligner.extend_left_gap_score = 0.0
    aligner.open_right_gap_score = 0.0
    aligner.extend_right_gap_score = 0.0
    return aligner


def protein_aligner() -> Align.PairwiseAligner:
    aligner = Align.PairwiseAligner(mode="global")
    aligner.substitution_matrix = substitution_matrices.load(PROTEIN_MATRIX)
    aligner.open_internal_gap_score = PROTEIN_OPEN_INTERNAL_GAP_SCORE
    aligner.extend_internal_gap_score = PROTEIN_EXTEND_INTERNAL_GAP_SCORE
    aligner.open_left_gap_score = 0.0
    aligner.extend_left_gap_score = 0.0
    aligner.open_right_gap_score = 0.0
    aligner.extend_right_gap_score = 0.0
    return aligner


def translate_from(nt: str, start: int) -> str:
    """Translate `nt[start:]` in frame. Any codon holding a non-ACGT character becomes `X`, and a
    trailing partial codon is dropped — the same tolerant rule `align.segment.translate` uses."""
    whole = len(nt) - start
    return segment.translate(nt[start : start + whole - whole % 3])


def has_internal_stop(aa: str) -> bool:
    """A stop anywhere but the final residue. The final one is the real terminator."""
    return "*" in aa[:-1]


def best_alignment(
    aligner: Align.PairwiseAligner, reference: str, query: str
) -> tuple[str, object, str]:
    """Semi-global align the query to the reference in both orientations; keep the better score.

    `[0]` is deterministic for a pinned Biopython, which is why `biopython` is an `==` pin.
    """
    forward = aligner.align(reference, query)[0]
    reverse_query = segment._revcomp(query)
    reverse = aligner.align(reference, reverse_query)[0]
    if reverse.score > forward.score:
        return REVERSE_COMPLEMENT, reverse, reverse_query
    return FORWARD, forward, query


def _nt_blocks(alignment: object) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    aligned = alignment.aligned  # type: ignore[attr-defined]
    return (
        [(int(a), int(b)) for a, b in aligned[0]],
        [(int(a), int(b)) for a, b in aligned[1]],
    )


def oriented_coding_start(cds: dict, strand: str, query_length: int) -> int | None:
    """0-based offset of the protein's first coding nucleotide in the *oriented* query.

    `None` when the GenBank strand and the aligner's chosen orientation disagree — then the caller
    infers the frame from the reference instead. Only `(forward, +)` and `(reverse_complement, -)`
    are self-consistent.
    """
    start, end = cds["start"], cds["end"]
    if strand == FORWARD and cds["strand"] == "+":
        return (start - 1) + (cds["codon_start"] - 1)
    if strand == REVERSE_COMPLEMENT and cds["strand"] == "-":
        # A deposited 1-based position p sits at oriented index (query_length - p); the protein's
        # first coding base is at deposited position end - (codon_start - 1).
        return query_length - (end - (cds["codon_start"] - 1))
    return None


def codon_blocks_from_aa(
    aa_alignment: object, ref_codon0: int, query_codon0: int
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """Impose a protein alignment back onto nucleotides, three at a time.

    `ref_codon0` / `query_codon0` are the 0-based nucleotide offsets of the first aligned codon.
    """
    ref_row, query_row = aa_alignment[0], aa_alignment[1]  # type: ignore[index]
    ref_blocks: list[tuple[int, int]] = []
    query_blocks: list[tuple[int, int]] = []
    ref_pos, query_pos = ref_codon0, query_codon0
    run: list[int] | None = None  # [ref_start, query_start, length_nt]
    for ref_char, query_char in zip(ref_row, query_row, strict=False):
        if ref_char != GAP and query_char != GAP:
            if run is None:
                run = [ref_pos, query_pos, 0]
            run[2] += 3
        elif run is not None:
            ref_blocks.append((run[0], run[0] + run[2]))
            query_blocks.append((run[1], run[1] + run[2]))
            run = None
        if ref_char != GAP:
            ref_pos += 3
        if query_char != GAP:
            query_pos += 3
    if run is not None:
        ref_blocks.append((run[0], run[0] + run[2]))
        query_blocks.append((run[1], run[1] + run[2]))
    return ref_blocks, query_blocks


def _cds_restricted(
    ref_blocks: list[tuple[int, int]],
    query_blocks: list[tuple[int, int]],
    cds_start0: int,
    cds_end0: int,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]]]:
    """The blocks clipped to the reference CDS span."""
    kept_ref: list[tuple[int, int]] = []
    kept_query: list[tuple[int, int]] = []
    for (t0, t1), (q0, _q1) in zip(ref_blocks, query_blocks, strict=False):
        low, high = max(t0, cds_start0), min(t1, cds_end0)
        if high > low:
            kept_ref.append((low, high))
            kept_query.append((q0 + (low - t0), q0 + (high - t0)))
    return kept_ref, kept_query


def _pdist(
    reference: str,
    oriented: str,
    ref_blocks: list[tuple[int, int]],
    query_blocks: list[tuple[int, int]],
    cds_start0: int,
    cds_end0: int,
) -> tuple[float | None, int]:
    """(nucleotide p-distance as a percentage, compared count) over the reference CDS span."""
    compared = mismatches = 0
    for (t0, t1), (q0, _q1) in zip(ref_blocks, query_blocks, strict=False):
        low, high = max(t0, cds_start0), min(t1, cds_end0)
        if high <= low:
            continue
        query_low = q0 + (low - t0)
        for offset in range(high - low):
            ref_base = reference[low + offset]
            query_base = oriented[query_low + offset]
            if ref_base in ACGT and query_base in ACGT:
                compared += 1
                mismatches += ref_base != query_base
    return (100.0 * mismatches / compared if compared else None), compared


def _aa_pdist(
    reference: str,
    oriented: str,
    ref_blocks: list[tuple[int, int]],
    query_blocks: list[tuple[int, int]],
    cds_start0: int,
    cds_end0: int,
) -> float | None:
    """Amino-acid p-distance (percent), translating each block in the reference codon frame."""
    compared = mismatches = 0
    for (t0, t1), (q0, _q1) in zip(ref_blocks, query_blocks, strict=False):
        low, high = max(t0, cds_start0), min(t1, cds_end0)
        if high <= low:
            continue
        offset = (3 - (low - cds_start0) % 3) % 3
        ref_low = low + offset
        query_low = q0 + (ref_low - t0)
        for index in range((high - ref_low) // 3):
            step = 3 * index
            ref_aa = segment.translate(reference[ref_low + step : ref_low + step + 3])
            query_aa = segment.translate(oriented[query_low + step : query_low + step + 3])
            if ref_aa != "X" and query_aa != "X":
                compared += 1
                mismatches += ref_aa != query_aa
    return (100.0 * mismatches / compared) if compared else None


def _tab_segment(
    reference: str,
    oriented: str,
    ref_from: int,
    ref_to: int,
    query_from: int,
    query_to: int,
    cds_start0: int,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], bool]:
    """TAB one frame-consistent segment, re-anchored to the global reference codon frame."""
    offset = (3 - (ref_from - cds_start0) % 3) % 3
    ref_codon0, query_codon0 = ref_from + offset, query_from + offset
    if ref_codon0 + 3 > ref_to or query_codon0 + 3 > query_to:
        return [], [], False
    ref_aa = translate_from(reference[ref_codon0:ref_to], 0)
    query_aa = translate_from(oriented[query_codon0:query_to], 0)
    if not ref_aa or not query_aa:
        return [], [], bool(query_aa) and has_internal_stop(query_aa)
    alignment = protein_aligner().align(ref_aa, query_aa)[0]
    ref_blocks, query_blocks = codon_blocks_from_aa(alignment, ref_codon0, query_codon0)
    return ref_blocks, query_blocks, has_internal_stop(query_aa)


def _recover_frameshift(
    reference: str,
    oriented: str,
    nt_ref_blocks: list[tuple[int, int]],
    nt_query_blocks: list[tuple[int, int]],
    cds_start0: int,
    cds_end0: int,
) -> tuple[list[tuple[int, int]], list[tuple[int, int]], bool]:
    """Split the CDS blocks where the net indel is non-×3, TAB each frame-consistent run, stitch.

    Returns `(ref_blocks, query_blocks, ok)`; `ok` is False if any segment still holds an internal
    stop, in which case the caller keeps plain nucleotide blocks over the CDS.
    """
    ref_segments, query_segments = _cds_restricted(
        nt_ref_blocks, nt_query_blocks, cds_start0, cds_end0
    )
    if not ref_segments:
        return [], [], False
    groups: list[tuple[list[tuple[int, int]], list[tuple[int, int]]]] = [
        ([ref_segments[0]], [query_segments[0]])
    ]
    for index in range(1, len(ref_segments)):
        deletion = ref_segments[index][0] - ref_segments[index - 1][1]
        insertion = query_segments[index][0] - query_segments[index - 1][1]
        if (insertion - deletion) % 3 != 0:
            groups.append(([ref_segments[index]], [query_segments[index]]))
        else:
            groups[-1][0].append(ref_segments[index])
            groups[-1][1].append(query_segments[index])

    all_ref: list[tuple[int, int]] = []
    all_query: list[tuple[int, int]] = []
    any_stop = False
    for group_ref, group_query in groups:
        ref_blocks, query_blocks, stop = _tab_segment(
            reference, oriented, group_ref[0][0], group_ref[-1][1],
            group_query[0][0], group_query[-1][1], cds_start0,
        )
        all_ref += ref_blocks
        all_query += query_blocks
        any_stop = any_stop or stop
    return all_ref, all_query, not any_stop


def codon_aware_align(
    aligner: Align.PairwiseAligner,
    reference: str,
    cds_span: tuple[int, int],
    query: str,
    query_cds: dict | None,
    *,
    pdist_guard_increase_pp: float,
    aa_guard_increase_pp: float,
    guard_bypass: bool = False,
) -> tuple[str, BlockAlignment, str]:
    """Codon-aware reference-anchored alignment. Returns `(strand, BlockAlignment, oriented)`.

    `cds_span` is the reference CDS as 1-based inclusive. Only CDS-span blocks are assembled — see
    the module docstring for why that is equivalent to upstream's whole-genome assembly.
    """
    cds_start0, cds_end0 = cds_span[0] - 1, cds_span[1]
    strand, nt_alignment, oriented = best_alignment(aligner, reference, query)
    nt_ref_blocks, nt_query_blocks = _nt_blocks(nt_alignment)

    def nucleotide_only(method: str) -> tuple[str, BlockAlignment, str]:
        kept_ref, kept_query = _cds_restricted(
            nt_ref_blocks, nt_query_blocks, cds_start0, cds_end0
        )
        return strand, BlockAlignment(
            ref_blocks=tuple(kept_ref), query_blocks=tuple(kept_query),
            method=method, internal_stop=False, recovered=None,
        ), oriented

    if not nt_ref_blocks:
        return nucleotide_only(METHOD_NT_FALLBACK)

    # Where the nucleotide anchor first and last touches the reference CDS. Both candidate frames
    # derive from this single anchor, so neither costs a re-alignment.
    anchor_ref_min: int | None = None
    anchor_query_min: int | None = None
    anchor_query_max: int | None = None
    for (t0, t1), (q0, _q1) in zip(nt_ref_blocks, nt_query_blocks, strict=False):
        low, high = max(t0, cds_start0), min(t1, cds_end0)
        if high > low:
            if anchor_query_min is None:
                anchor_ref_min, anchor_query_min = low, q0 + (low - t0)
            anchor_query_max = q0 + (high - t0)
    if anchor_query_min is None:
        return nucleotide_only(METHOD_NT_FALLBACK)
    assert anchor_ref_min is not None and anchor_query_max is not None

    ref_offset = (3 - (anchor_ref_min - cds_start0) % 3) % 3
    inferred_start = anchor_query_min + ref_offset
    inferred_end = min(anchor_query_max, len(oriented))

    def assemble(
        query_cds_start: int, query_cds_end: int, method: str
    ) -> tuple[list, list, str, bool, bool | None] | None:
        query_end = min(query_cds_end, len(oriented))
        if query_end - query_cds_start < 3:
            return None
        query_aa = translate_from(oriented[query_cds_start:query_end], 0)
        internal_stop = has_internal_stop(query_aa)
        recovered: bool | None = None
        if internal_stop:
            ref_blocks, query_blocks, ok = _recover_frameshift(
                reference, oriented, nt_ref_blocks, nt_query_blocks, cds_start0, cds_end0
            )
            if ok and ref_blocks:
                method, recovered = METHOD_RECOVERED, True
            else:
                ref_blocks, query_blocks = _cds_restricted(
                    nt_ref_blocks, nt_query_blocks, cds_start0, cds_end0
                )
                method, recovered = METHOD_NT_CDS_FALLBACK, False
        else:
            ref_aa = translate_from(reference[cds_start0:cds_end0], 0)
            alignment = protein_aligner().align(ref_aa, query_aa)[0]
            ref_blocks, query_blocks = codon_blocks_from_aa(
                alignment, cds_start0, query_cds_start
            )
        if not ref_blocks:
            return None
        return ref_blocks, query_blocks, method, internal_stop, recovered

    annotated_start = (
        oriented_coding_start(query_cds, strand, len(oriented)) if query_cds else None
    )
    if annotated_start is None:
        result = assemble(inferred_start, inferred_end, METHOD_CODON_REF_INFERRED)
    else:
        annotated_start = max(0, min(annotated_start, len(oriented)))
        result = assemble(annotated_start, anchor_query_max, METHOD_CODON)
        # The amino-acid guard: a clean annotated frame that differs from the inferred one, and
        # is dramatically worse at the protein level, is a broken `codon_start`.
        if (
            result is not None
            and result[3] is False
            and (annotated_start, anchor_query_max) != (inferred_start, inferred_end)
        ):
            inferred = assemble(inferred_start, inferred_end, METHOD_CODON_REF_INFERRED)
            if inferred is not None and inferred[3] is False:
                annotated_aa = _aa_pdist(
                    reference, oriented, result[0], result[1], cds_start0, cds_end0
                )
                inferred_aa = _aa_pdist(
                    reference, oriented, inferred[0], inferred[1], cds_start0, cds_end0
                )
                if (
                    annotated_aa is not None
                    and inferred_aa is not None
                    and annotated_aa - inferred_aa > aa_guard_increase_pp
                ):
                    result = inferred

    if result is None:
        return nucleotide_only(METHOD_NT_FALLBACK)
    ref_blocks, query_blocks, method, internal_stop, recovered = result

    # The nucleotide guard: never let codon-awareness worsen the metric the tiering rests on.
    codon_pdist, _ = _pdist(
        reference, oriented, ref_blocks, query_blocks, cds_start0, cds_end0
    )
    anchor_pdist, _ = _pdist(
        reference, oriented, nt_ref_blocks, nt_query_blocks, cds_start0, cds_end0
    )
    if (
        not guard_bypass
        and codon_pdist is not None
        and anchor_pdist is not None
        and codon_pdist - anchor_pdist > pdist_guard_increase_pp
    ):
        return nucleotide_only(METHOD_NT_BETTER)

    return strand, BlockAlignment(
        ref_blocks=tuple(ref_blocks), query_blocks=tuple(query_blocks),
        method=method, internal_stop=internal_stop, recovered=recovered,
    ), oriented


def project(
    alignment: BlockAlignment, oriented: str, cds_start0: int, cds_end0: int
) -> str:
    """Write the aligned query onto the reference CDS coordinate frame.

    Fixed width by construction. A reference position the query does not cover — whether unsequenced
    flank or true deletion — is a gap; a query base with no reference position is dropped.
    """
    width = cds_end0 - cds_start0
    row = [GAP] * width
    for (t0, t1), (q0, _q1) in zip(alignment.ref_blocks, alignment.query_blocks, strict=False):
        low, high = max(t0, cds_start0), min(t1, cds_end0)
        if high <= low:
            continue
        query_low = q0 + (low - t0)
        for offset in range(high - low):
            row[low - cds_start0 + offset] = oriented[query_low + offset]
    return "".join(row)


def _gap_audit(
    row: str, alignment: BlockAlignment, cds_start0: int, cds_end0: int
) -> tuple[int, int]:
    """(non-×3 gap runs, mis-phased ×3 gap runs) over the record's *covered* span only.

    The uncovered CDS flanks of a partial record are unsequenced, not deletions; counting them would
    make every fragment look frameshifted.
    """
    if not alignment.ref_blocks:
        return 0, 0
    covered_start = max(cds_start0, min(block[0] for block in alignment.ref_blocks))
    covered_end = min(cds_end0, max(block[1] for block in alignment.ref_blocks))
    if covered_end <= covered_start:
        return 0, 0
    non_multiple = misphased = 0
    span = row[covered_start - cds_start0 : covered_end - cds_start0]
    run_start = None
    for index, character in enumerate(span + "X"):
        if character == GAP:
            if run_start is None:
                run_start = index
        elif run_start is not None:
            length = index - run_start
            if length % 3 != 0:
                non_multiple += 1
            elif (covered_start + run_start - cds_start0) % 3 != 0:
                misphased += 1
            run_start = None
    return non_multiple, misphased


@dataclass(frozen=True)
class AnchorInputs:
    """Everything the anchored stack needs out of `final/`, read once.

    Exists so a caller can do all of its `final/` reading *before* arming the tool-exec guard,
    which shares `sandbox`'s path rules and so refuses reads of the shipped release. `align/` may
    read `final/` — the documented boundary exception — but only outside the guarded window, and
    hoisting the reads here makes that separation structural rather than incidental.
    """

    region_rows: tuple[regions.Region, ...]
    cds_by_record: dict[str, list[dict]]
    parts_by_feature: dict[str, list[dict]]
    codon_starts: dict[str, str]


def load_anchor_inputs(repository_root: Path) -> AnchorInputs:
    cds_by_record, parts_by_feature, codon_starts = segment._load_cds_index(repository_root)
    return AnchorInputs(
        region_rows=tuple(regions.derive_regions(repository_root)),
        cds_by_record=cds_by_record,
        parts_by_feature=parts_by_feature,
        codon_starts=codon_starts,
    )


def build_anchored_cds_block(
    population: AlignmentPopulation,
    repository_root: Path | None = None,
    *,
    inputs: AnchorInputs | None = None,
) -> AnchoredCdsBlock:
    """The CDS block for one anchored artifact. Pure Biopython — no aligner binary, no scratch.

    Supply `inputs` when the tool guard is (or will be) armed; `repository_root` is the convenience
    path for unguarded callers such as tests, and reads the same tables itself.
    """
    spec = population.spec.anchor
    if spec is None:
        raise ContractError(f"{population.spec.name} has no declared AnchorSpec")
    if inputs is None:
        if repository_root is None:
            raise ContractError("build_anchored_cds_block needs either repository_root or inputs")
        inputs = load_anchor_inputs(repository_root)

    region_rows = [row for row in inputs.region_rows if row.serotype == spec.serotype]
    if not region_rows:
        raise ContractError(f"no derived regions for {spec.serotype}")
    by_region = {row.region: row for row in region_rows}
    cds_start, cds_end = by_region["VP4"].start, by_region["3D"].end
    reference_accession = by_region["VP4"].ref_accession
    if reference_accession != spec.reference_accession:
        raise ContractError(
            f"{spec.serotype}: derived regions name reference {reference_accession}, but the "
            f"AnchorSpec declares {spec.reference_accession}"
        )

    by_accession = {record.accession: record for record in population.records}
    reference_record = by_accession.get(spec.reference_accession)
    if reference_record is None:
        raise ContractError(
            f"{spec.reference_accession} is not in the {population.spec.name} population, so the "
            f"reference row it anchors cannot come from the population itself"
        )
    reference = reference_record.sequence

    cds_start0, cds_end0 = cds_start - 1, cds_end

    aligner = nucleotide_aligner()
    aligned_nt: dict[str, str] = {}
    rows: list[AnchoredRow] = []
    over_cap: list[str] = []

    for record in population.records:
        if record.length_nt > spec.length_cap:
            over_cap.append(record.accession)

        # Keyed on `version`, not `accession`: `record_id` in the feature tables is the versioned
        # id, and `align.segment` looks it up the same way.
        query_cds = _query_cds_frame(
            record.version, inputs.cds_by_record, inputs.parts_by_feature, inputs.codon_starts
        )
        strand, alignment, oriented = codon_aware_align(
            aligner, reference, (cds_start, cds_end), record.sequence, query_cds,
            pdist_guard_increase_pp=spec.pdist_guard_increase_pp,
            aa_guard_increase_pp=spec.aa_guard_increase_pp,
            guard_bypass=record.accession in spec.pdist_guard_bypass,
        )
        row = project(alignment, oriented, cds_start0, cds_end0)
        non_multiple, misphased = _gap_audit(row, alignment, cds_start0, cds_end0)
        # Only rows that actually carry a residue enter `aligned_nt`. A record whose alignment lands
        # wholly outside the CDS span — a 5'UTR-only fragment, say — projects to an all-gap row, and
        # publishing that as a *present* block would make "absent" indistinguishable from "covered
        # but entirely deleted" in the coverage sidecar. It still gets an all-gap span in the
        # stitched row (`align.stitch` pads it identically), so the alignment bytes are unchanged;
        # what changes is that the sidecar now says the block is absent, with a reason. Every record
        # stays in `rows` regardless, so the audit trail is complete.
        if row.count(GAP) < len(row):
            aligned_nt[record.accession] = row
        rows.append(
            AnchoredRow(
                accession=record.accession, strand=strand, method=alignment.method,
                internal_stop=alignment.internal_stop, recovered=alignment.recovered,
                cds_row=row, n_cds_gap_non_multiple_of_three=non_multiple,
                n_cds_gap_misphased=misphased,
            )
        )

    return AnchoredCdsBlock(
        serotype=spec.serotype,
        reference_accession=spec.reference_accession,
        cds_start=cds_start,
        cds_end=cds_end,
        width_nt=cds_end0 - cds_start0,
        reference_row=reference[cds_start0:cds_end0],
        aligned_nt=aligned_nt,
        rows=tuple(rows),
        over_length_cap=tuple(sorted(over_cap)),
    )


def _query_cds_frame(
    version: str,
    cds_by_record: dict[str, list[dict]],
    parts_by_feature: dict[str, list[dict]],
    codon_starts: dict[str, str],
) -> dict | None:
    """The primary CDS as `{start, end, strand, codon_start}` in deposited 1-based coordinates.

    `None` when the record has no CDS annotation or an unusable `codon_start` — the caller then
    infers the frame from the reference, which is upstream's own behaviour for both cases.
    """
    features = cds_by_record.get(version)
    if not features:
        return None
    span_by_feature: dict[str, tuple[int, int]] = {}
    for feature in features:
        parts = parts_by_feature.get(feature["feature_id"])
        if not parts:
            continue
        start, end, _strand = segment._outer_span_and_strand(parts)
        span_by_feature[feature["feature_id"]] = (start, end)
    usable = [f for f in features if f["feature_id"] in span_by_feature]
    if not usable:
        return None
    primary = segment._primary_cds(usable, span_by_feature)
    feature_id = primary["feature_id"]
    start, end, strand = segment._outer_span_and_strand(parts_by_feature[feature_id])
    try:
        codon_start = segment._codon_start(feature_id, codon_starts)
    except ContractError:
        return None
    return {"start": start, "end": end, "strand": strand or "+", "codon_start": codon_start}
