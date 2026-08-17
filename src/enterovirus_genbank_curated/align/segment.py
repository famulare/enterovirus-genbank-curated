"""One segmentation pass over every canonical record: the primary CDS split into 5'NCR / ORF /
3'NCR, or a 6-frame inference fallback when no CDS is annotated at all.

Ported from the upstream `build_ev_segmentation.py` (`build_polio_segmentation.py` re-used its logic
verbatim, pointed at a different carve). Upstream ran this twice — once per carve — and merged the
two caches; here it runs once over the whole union, the same simplification `align.population`
already made for tiering.

## Where this diverges from upstream, and why

Upstream's `genbank_features.csv` collapsed every multi-part (`join`) CDS to its outer
`(min(starts), max(ends))` span before segmentation ever saw it, so a multi-part CDS was translated
straight through as if the space between its parts were coding. This repo's
`feature_location_parts.tsv.gz` keeps each location part with its own bounds, strand and
`part_ordinal` — which is `enumerate()` over Biopython's own, already-reordered `.parts` list (not
raw file-declaration order) — so a multi-part CDS can be *spliced* properly instead: concatenate
each part's own substring, individually reverse-complemented per its own strand, in `part_ordinal`
order. That is exactly what `Bio.SeqFeature.CompoundLocation.extract()` does, and it was measured
empirically before this module was written: for a real `complement(join(1..10,20..30))` feature,
Biopython's parser stores `.parts` as `[19:30], [0:10]` — reversed from file order — so a naive
same-order concatenation of individually-revcomp'd parts already gives the biologically correct
transcript. `part_ordinal` inherits that same reordering, so sorting by it and concatenating
reproduces `.extract()` without needing to re-derive Biopython's reordering rule here.

Everything else is a direct port: the trailing-partial-codon truncation, the annotated/inferred
acceptance gate, and the 6-frame inference fallback are all upstream's exact logic, renamed to this
module's naming.

## The inference path chooses by homology, not by length

Upstream's `inferred_orf` — carried here verbatim until 2026-08-16 — took the **longest stop-free
run** across six frames. Nothing in that rule consults whether the run reads as protein, and on
release 5.0.0's shipped bytes it chose a wrong frame for 51 records in `EV_unified` and 20 in
`NPEV_unified`. The failure is not subtle: a 1,105 nt PV3 VP1 fragment (`OR538734`) happened to
carry a 368-codon stop-free run in frame +1, which beat the true frame's longest run because the
true frame contains two stop codons. Frame +1 shares 1.9% of its 6-mers with this corpus's own
annotated proteins; frame +3 shares 74.9%.

So `_candidate_orfs` now enumerates *every* stop-free run in all six frames and `_inferred_orf`
scores each against a pool built from the annotated path's own output, taking the best. Ties break
on length and then on `(strand, frame, offset)`, so the choice is a function of the sequence and the
corpus, never of iteration order.

## A record with no coding content is `noncoding`, and keeps its sequence

The same score answers a second question the old rule could not even ask: whether the record codes
for anything at all. 1,281 `EV_unified` rows scored below `infer_min_homology` in every frame, and
1,261 of the 1,262 that map to a reference at all are pure 5'UTR amplicons — the standard pan-
enterovirus RT-PCR product, ~170-570 on the reference. Under the old rule each of them was handed a
spurious >=20 aa ORF, placed in the CDS block as protein, *and* excluded from the 5'NCR block, on
the grounds that an inferred frame's boundaries are not trustworthy.

That reasoning is right about an inferred frame and wrong about this case: a record with no frame at
all has no boundaries to distrust. Such a record now takes `method="noncoding"`, contributes no CDS
row, and offers its whole sequence to the 5' side, where `structural.classify_fragment` and the
covariance model decide whether it belongs. It is offered to the 5' side only — 1,261 of 1,262 are
5'UTR, the one exception maps to the 3' end, and the 3'UTR is ~70 nt against the 5'UTR's ~740, so a
several-hundred-nucleotide non-coding enterovirus amplicon is a 5'UTR product by construction.

`method="none"` survives, and now means something it never quite did: *neither* pool recognises the
record. Being unrecognisable as protein is not by itself evidence of being 5'UTR, and treating it
that way would push a 51 nt fragment that is neither — there are 116, mostly tiny patent deposits —
straight into a 738-column covariance model that will force-align anything it is handed. That is
the same error as the one this section repairs, committed in the other block. So a record reaches
the 5' side only if it reads as 5'UTR, and places nothing at all otherwise.

## Ragged (fuzzy) bounds are not special-cased

63% of this corpus's CDS features have a `BeforePosition`/`AfterPosition` bound (GenBank's
`<1..>7440` ambiguous-end notation) rather than an `ExactPosition` one. Upstream never
distinguished these — Biopython's fuzzy position classes are `int` subclasses, so `int(bound)`
silently drops the `<`/`>` marker and treats the position as if it were exact. That is the actual,
measured behavior of the code this module ports, so it is carried forward rather than "fixed": a
ragged bound is used at its plain numeric value, with no truncation, no flag, and no record of the
fuzziness anywhere downstream. If a ragged CDS produces a length not divisible by 3, that is exactly
what the trailing-partial-codon rule below already exists to absorb.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from Bio.Seq import Seq

from enterovirus_genbank_curated.align import contract
from enterovirus_genbank_curated.align.population import AlignedRecord
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.oracle.release import read_tsv_gz

CDS_FEATURE_KEY = "CDS"
CODON_START_QUALIFIER = "codon_start"

# A record with no CDS feature at all, whose 6-frame inference also failed.
ABSENCE_NO_CDS_UNTRANSLATABLE = "no_cds_untranslatable"
# A record with a CDS feature, but one that failed the annotated-acceptance gate, whose 6-frame
# inference also failed.
ABSENCE_ANNOTATED_REJECTED_UNTRANSLATABLE = "annotated_rejected_untranslatable"
# An ORF was found, and no frame of it reads as enterovirus protein. Distinct from the two above:
# those say "nothing translatable was found", this says "something was found and it is not coding".
# The 5'UTR amplicons land here.
ABSENCE_NO_CODING_HOMOLOGY = "no_coding_homology"
# Neither pool recognises this record: no frame reads as protein *and* the sequence does not read as
# 5'UTR either. It places nothing, which is the honest outcome and the one `method="none"` exists
# for. 116 records, mostly 15-51 nt patent deposits.
ABSENCE_NO_CODING_OR_NCR_HOMOLOGY = "no_coding_or_ncr_homology"

_DEFAULT_CODON_SPEC = contract.CodonSpec()

# The whole IUPAC set, not just ACGTN. `str.maketrans("ACGTN", "TGCAN")` passes every other
# ambiguity code through unchanged, so the reverse complement of an `R` (A-or-G) came back as `R`
# where it should be `Y` (C-or-T) — a wrong base, not a lost one, and one the translator hides
# because both spell `X`. Measured on release 5.0.0's shipped bytes before this was fixed: of 728
# records carrying a non-`N` ambiguity code, 2 are placed reverse-complemented in `EV_unified` with
# such a code inside the placed span — `JX006787` and `JN393113`, one nucleotide each. Those two
# nucleotides carry the old value until the next alignment rebuild is promoted; nothing else in the
# release is reachable from here.
_IUPAC = "ACGTNRYWSKMBDHV"
_IUPAC_COMPLEMENT = "TGCANYRWSMKVHDB"
_COMPLEMENT = str.maketrans(
    _IUPAC + _IUPAC.lower(), _IUPAC_COMPLEMENT + _IUPAC_COMPLEMENT.lower()
)
_CODON_TABLE = {
    a + b + c: str(Seq(a + b + c).translate()) for a in "ACGT" for b in "ACGT" for c in "ACGT"
}


def _revcomp(sequence: str) -> str:
    return sequence.translate(_COMPLEMENT)[::-1]


def translate(nt: str) -> str:
    """Whole-codon translation; anything outside the plain-ACGT table — an ambiguity code, or a
    trailing partial codon — becomes `X`, exactly as upstream's lookup-or-`X` table."""
    return "".join(_CODON_TABLE.get(nt[i : i + 3], "X") for i in range(0, len(nt) - len(nt) % 3, 3))


@dataclass(frozen=True)
class Segmentation:
    """One record's segmentation result.

    `ncr5`/`ncr3` are populated on the annotated path, where the CDS bounds say where the NCRs are.
    An *inferred* frame's boundaries are not trustworthy, so it still carries no NCR at all. A
    `noncoding` record is the third case and the reason this docstring changed: it has no frame, so
    there are no boundaries to distrust, and its whole sequence goes into `ncr5`.
    """

    accession: str
    method: Literal["annotated", "inferred", "noncoding", "none"]
    strand: Literal["+", "-", ""]
    ncr5: str
    ncr3: str
    orf_nt: str
    aa: str
    n_internal_stops: int
    absence_reason: str | None
    # How many nucleotides `_drop_internal_ambiguous_runs` removed from `orf_nt`. Non-zero only for
    # a deposit padded across an assembly gap. It is carried to the coverage sidecar rather than
    # left implicit, because without it a padded gap and a real deletion look identical in the
    # shipped row.
    unsequenced_nt: int = 0


# --- the homology pool the inference path is judged against --------------------------------------


def _kmers(text: str, size: int) -> set[str]:
    return {text[i : i + size] for i in range(len(text) - size + 1)}


@dataclass(frozen=True)
class HomologyPool:
    """What "reads as enterovirus" means, derived from the corpus rather than declared.

    `protein` is the 6-mer set of every annotated-path polyprotein at or above
    `CodonSpec.infer_pool_min_aa`; `ncr5` is the 12-mer set of every annotated-path 5'NCR fragment.
    Both come from records whose GenBank CDS annotation was accepted, so the pool is built entirely
    from the part of the corpus that never needed inference — the population being judged does not
    get to vote on itself.

    Passed explicitly rather than defaulted. An empty pool would classify every inferred record as
    `noncoding` and empty the CDS block, which `align.codon` fails on loudly; making the caller
    supply it means that failure is reachable only by supplying nothing, never by forgetting.
    """

    protein: frozenset[str]
    ncr5: frozenset[str]
    protein_kmer: int
    ncr5_kmer: int
    n_proteins: int

    def protein_homology(self, aa: str) -> float:
        """Fraction of this peptide's 6-mers the pool has seen. Stop and ambiguity characters break
        the k-mer rather than being spelled through: an `X` matches nothing, and letting it sit
        inside a k-mer would only dilute both sides of the ratio."""
        if not self.protein:
            return 0.0
        kmers = set()
        for run in aa.replace("*", "X").split("X"):
            kmers |= _kmers(run, self.protein_kmer)
        if not kmers:
            return 0.0
        return len(kmers & self.protein) / len(kmers)

    def ncr5_homology(self, nt: str) -> float:
        if not self.ncr5:
            return 0.0
        kmers = _kmers(nt.upper(), self.ncr5_kmer)
        if not kmers:
            return 0.0
        return len(kmers & self.ncr5) / len(kmers)


EMPTY_POOL = HomologyPool(
    protein=frozenset(), ncr5=frozenset(), protein_kmer=0, ncr5_kmer=0, n_proteins=0
)


def build_homology_pool(
    segmentations: dict[str, Segmentation], spec: contract.CodonSpec
) -> HomologyPool:
    protein: set[str] = set()
    ncr5: set[str] = set()
    n_proteins = 0
    for segmentation in segmentations.values():
        if segmentation.method != "annotated":
            continue
        if len(segmentation.aa) >= spec.infer_pool_min_aa:
            for run in segmentation.aa.replace("*", "X").split("X"):
                protein |= _kmers(run, spec.infer_kmer_size)
            n_proteins += 1
        if segmentation.ncr5:
            ncr5 |= _kmers(segmentation.ncr5.upper(), spec.noncoding_orient_kmer)
    return HomologyPool(
        protein=frozenset(protein),
        ncr5=frozenset(ncr5),
        protein_kmer=spec.infer_kmer_size,
        ncr5_kmer=spec.noncoding_orient_kmer,
        n_proteins=n_proteins,
    )


# --- the trailing-partial-codon rule, ported verbatim from upstream's `_finish` ------------------


def _finish(raw_coding: str) -> tuple[str, str, int]:
    """Truncate to a whole number of codons, translate, drop a trailing stop if present.

    Any leftover 1-2 nt — from codon_start offsetting, an annotated end that is off by one, or a
    ragged bound used at its plain numeric value — is silently dropped: `raw_coding[:len -
    len%3]`. `n_internal_stops` is counted *before* masking; the returned amino-acid string has
    every stop, trailing or internal, replaced with `X`.
    """
    trimmed = raw_coding[: len(raw_coding) - len(raw_coding) % 3]
    aa = translate(trimmed)
    if aa.endswith("*"):
        aa = aa[:-1]
        trimmed = trimmed[:-3]
    n_internal_stops = aa.count("*")
    return trimmed, aa.replace("*", "X"), n_internal_stops


# --- multi-part splicing --------------------------------------------------------------------------


def _splice(parts: list[dict], sequence: str, feature_id: str) -> str:
    """Concatenate each part's own substring, individually reverse-complemented per its own
    strand, in `part_ordinal` order — see the module docstring for why this reproduces
    `CompoundLocation.extract()` exactly, including for a minus-strand join."""
    if not parts:
        raise ContractError(f"{feature_id} has no location parts")
    ordered = sorted(parts, key=lambda part: int(part["part_ordinal"]))
    pieces = []
    for part in ordered:
        start, end = int(part["start_1based"]), int(part["end_1based_inclusive"])
        piece = sequence[start - 1 : end]
        if part["strand"] == "-":
            piece = _revcomp(piece)
        pieces.append(piece)
    return "".join(pieces)


def _outer_span_and_strand(parts: list[dict]) -> tuple[int, int, str]:
    """The bracketing span used only to place the NCR blocks, never the coding sequence itself.

    A blank strand (parts that disagree) is treated the same as forward, exactly as upstream's
    `annotated_segmentation` did (`strand in ("+", "")`) — a genuinely mixed-strand join is a
    theoretical case this corpus's real CDS features never exercise (see the module docstring).
    """
    starts = [int(part["start_1based"]) for part in parts]
    ends = [int(part["end_1based_inclusive"]) for part in parts]
    strands = {part["strand"] for part in parts}
    strand = next(iter(strands)) if len(strands) == 1 else ""
    return min(starts), max(ends), strand


def _codon_start(feature_id: str, codon_starts: dict[str, str]) -> int:
    raw = codon_starts.get(feature_id)
    if raw is None:
        raise ContractError(f"{feature_id} has no {CODON_START_QUALIFIER} qualifier")
    try:
        value = int(raw)
    except ValueError:
        raise ContractError(
            f"{feature_id} {CODON_START_QUALIFIER}={raw!r} is not an integer"
        ) from None
    if value not in (1, 2, 3):
        raise ContractError(f"{feature_id} {CODON_START_QUALIFIER}={value} is not 1, 2 or 3")
    return value


def _annotated(
    sequence: str, feature_id: str, parts: list[dict], codon_starts: dict[str, str]
) -> tuple[str, str, str, str, int, str]:
    """(ncr5, ncr3, orf_nt, aa, n_internal_stops, strand_used)."""
    spliced = _splice(parts, sequence, feature_id)
    codon_start = _codon_start(feature_id, codon_starts)
    if codon_start > len(spliced):
        raise ContractError(
            f"{feature_id}: codon_start={codon_start} exceeds the {len(spliced)} nt spliced CDS"
        )
    orf_nt, aa, n_internal_stops = _finish(spliced[codon_start - 1 :])

    outer_start, outer_end, strand = _outer_span_and_strand(parts)
    length = len(sequence)
    if strand == "-":
        oriented = _revcomp(sequence)
        cds_lo, cds_hi = length - outer_end, length - outer_start + 1
    else:
        oriented = sequence
        cds_lo, cds_hi = outer_start - 1, outer_end
    ncr5, ncr3 = oriented[:cds_lo], oriented[cds_hi:]
    return ncr5, ncr3, orf_nt, aa, n_internal_stops, (strand or "+")


def _primary_cds(cds_features: list[dict], span_by_feature: dict[str, tuple[int, int]]) -> dict:
    """The polyprotein CDS: the longest by outer span. Ties keep the first-encountered feature —
    `cds_features` is in `feature_ordinal` (annotation) order, so this matches upstream's
    `max()`-over-a-list, first-occurrence tie-break exactly."""

    def span_width(feature: dict) -> int:
        start, end = span_by_feature[feature["feature_id"]]
        return end - start

    return max(cds_features, key=span_width)


# --- the 6-frame inference fallback ---------------------------------------------------------------


@dataclass(frozen=True)
class _Candidate:
    strand: str
    frame: int
    offset: int
    orf_nt: str
    aa: str

    @property
    def order_key(self) -> tuple[str, int, int]:
        """The deterministic tie-break, applied only after homology and length have both tied."""
        return (self.strand, self.frame, self.offset)


def _candidate_orfs(sequence: str, spec: contract.CodonSpec) -> list[_Candidate]:
    """Every stop-free run in all six frames that clears `infer_min_aa` and the X-fraction gate.

    Upstream's `_longest_orf` kept only the longest run per strand and threw the rest away before
    anything could look at them, which is why a wrong frame could win: the true frame's runs were
    already gone. Enumerating them all costs one pass over six translations and is what lets the
    caller choose on evidence.
    """
    candidates: list[_Candidate] = []
    for oriented, strand in ((sequence, "+"), (_revcomp(sequence), "-")):
        for frame in range(3):
            aa_full = translate(oriented[frame:])
            position = 0
            for run in aa_full.split("*"):
                if len(run) >= spec.infer_min_aa and (
                    run.count("X") / len(run) <= spec.infer_max_x_fraction
                ):
                    nt0 = frame + position * 3
                    nt1 = frame + (position + len(run)) * 3
                    candidates.append(
                        _Candidate(
                            strand=strand, frame=frame, offset=nt0,
                            orf_nt=oriented[nt0:nt1], aa=run,
                        )
                    )
                position += len(run) + 1
    return candidates


def _inferred_orf(
    sequence: str, spec: contract.CodonSpec, pool: HomologyPool
) -> tuple[str, str, str, float] | None:
    """The best-scoring candidate ORF as `(orf_nt, aa, strand, homology)`, or `None` if there is no
    candidate at all. No NCR either way — an inferred frame's boundaries are not trustworthy.

    A returned homology below `spec.infer_min_homology` is not an error here; `segment_one` reads it
    and routes the record to `noncoding`. Keeping the score rather than the verdict means the
    threshold is applied in exactly one place.
    """
    candidates = _candidate_orfs(sequence, spec)
    if not candidates:
        return None
    scored = [(pool.protein_homology(c.aa), len(c.aa), c.order_key, c) for c in candidates]
    homology, _length, _key, best = max(scored, key=lambda s: s[:3])
    return best.orf_nt, best.aa, best.strand, homology


def _drop_ambiguous_runs(
    orf_nt: str, aa: str, spec: contract.CodonSpec
) -> tuple[str, str, int]:
    """Remove runs of `drop_ambiguous_run_aa` or more wholly-unsequenced codons from the ORF.

    "Wholly unsequenced" is read off the nucleotides, not off the `X` in the translation, and that
    distinction is load-bearing: `_finish` masks a real internal stop codon to `X` too, and a stop
    codon is sequence. A codon goes only if not one of its three bases is a plain A/C/G/T, which is
    the same predicate `align.codon.drop_unsequenced_codon_columns` applies one stage later — this
    one just gets there before MAFFT has to place it.

    `aa` and `orf_nt` are cut together, so the caller's `len(aa) * 3 == len(orf_nt)` invariant — the
    one `codon.backtranslate` rests on — holds across the cut.
    """
    if not orf_nt:
        return orf_nt, aa, 0
    unsequenced = [
        all(base not in "ACGT" for base in orf_nt[i * 3 : i * 3 + 3]) for i in range(len(aa))
    ]
    doomed: set[int] = set()
    start = 0
    while start < len(unsequenced):
        if not unsequenced[start]:
            start += 1
            continue
        end = start
        while end < len(unsequenced) and unsequenced[end]:
            end += 1
        if end - start >= spec.drop_ambiguous_run_aa:
            doomed.update(range(start, end))
        start = end
    if not doomed:
        return orf_nt, aa, 0
    kept_nt = "".join(orf_nt[i * 3 : i * 3 + 3] for i in range(len(aa)) if i not in doomed)
    kept_aa = "".join(aa[i] for i in range(len(aa)) if i not in doomed)
    return kept_nt, kept_aa, 3 * len(doomed)


def _oriented_noncoding(sequence: str, pool: HomologyPool) -> tuple[str, str]:
    """`(sequence in the orientation the 5'NCR pool prefers, strand)`.

    A tie keeps the deposit as it stands: `>` rather than `>=` means a sequence the pool cannot
    distinguish is not silently reverse-complemented on the strength of nothing.
    """
    forward = pool.ncr5_homology(sequence)
    reverse_sequence = _revcomp(sequence)
    if pool.ncr5_homology(reverse_sequence) > forward:
        return reverse_sequence, "-"
    return sequence, "+"


# --- feature-table loading -----------------------------------------------------------------------


def _load_cds_index(
    repository_root: Path,
) -> tuple[dict[str, list[dict]], dict[str, list[dict]], dict[str, str]]:
    """(CDS features by record_id, location parts by feature_id, codon_start by feature_id), over
    CDS features only — everything else in these three tables is read once and discarded."""
    f_header, f_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURES)
    cds_by_record: dict[str, list[dict]] = {}
    cds_feature_ids: set[str] = set()
    for row in f_rows:
        feature = dict(zip(f_header, row, strict=False))
        if feature["feature_key"] != CDS_FEATURE_KEY:
            continue
        cds_feature_ids.add(feature["feature_id"])
        cds_by_record.setdefault(feature["record_id"], []).append(feature)

    p_header, p_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURE_PARTS)
    parts_by_feature: dict[str, list[dict]] = {}
    for row in p_rows:
        part = dict(zip(p_header, row, strict=False))
        if part["feature_id"] not in cds_feature_ids:
            continue
        parts_by_feature.setdefault(part["feature_id"], []).append(part)

    q_header, q_rows = read_tsv_gz(repository_root / contract.SOURCE_FEATURE_QUALIFIERS)
    codon_starts: dict[str, str] = {}
    for row in q_rows:
        qualifier = dict(zip(q_header, row, strict=False))
        if qualifier["qualifier_name"] != CODON_START_QUALIFIER:
            continue
        if qualifier["feature_id"] not in cds_feature_ids:
            continue
        codon_starts[qualifier["feature_id"]] = qualifier["qualifier_value"]

    return cds_by_record, parts_by_feature, codon_starts


# --- the per-record entry point, and the whole-population pass -----------------------------------


def segment_one(
    accession: str,
    sequence: str,
    version: str,
    cds_by_record: dict[str, list[dict]],
    parts_by_feature: dict[str, list[dict]],
    codon_starts: dict[str, str],
    spec: contract.CodonSpec,
    pool: HomologyPool,
) -> Segmentation:
    cds_features = cds_by_record.get(version, [])
    seg: tuple[str, str, str, str, int, str] | None = None
    if cds_features:
        span_by_feature = {
            feature["feature_id"]: (
                min(int(part["start_1based"]) for part in parts_by_feature[feature["feature_id"]]),
                max(
                    int(part["end_1based_inclusive"])
                    for part in parts_by_feature[feature["feature_id"]]
                ),
            )
            for feature in cds_features
        }
        primary = _primary_cds(cds_features, span_by_feature)
        ncr5, ncr3, orf_nt, aa, n_internal_stops, strand_used = _annotated(
            sequence, primary["feature_id"], parts_by_feature[primary["feature_id"]], codon_starts
        )
        if n_internal_stops <= spec.accept_annotated_max_internal_stops and (
            len(aa) >= spec.accept_annotated_min_aa
        ):
            seg = (ncr5, ncr3, orf_nt, aa, n_internal_stops, strand_used)

    if seg is not None:
        ncr5, ncr3, orf_nt, aa, n_internal_stops, strand_used = seg
        orf_nt, aa, unsequenced_nt = _drop_ambiguous_runs(orf_nt, aa, spec)
        # A CDS annotated across nothing but padding empties here. No such deposit exists today —
        # the worst carries 749 X of 1,797 aa — but an empty `aa` would reach MAFFT as a
        # zero-length FASTA record, and "we would have noticed" is not a guarantee. A record with no
        # sequenced CDS at all has no business in the CDS block, which is what the fall-through
        # below already says for every other way of having no ORF.
        if aa:
            return Segmentation(
                accession=accession,
                method="annotated",
                strand=strand_used,
                ncr5=ncr5,
                ncr3=ncr3,
                orf_nt=orf_nt,
                aa=aa,
                n_internal_stops=n_internal_stops,
                absence_reason=None,
                unsequenced_nt=unsequenced_nt,
            )

    inferred = _inferred_orf(sequence, spec, pool)
    oriented, strand_used = _oriented_noncoding(sequence, pool)
    ncr5_homology = pool.ncr5_homology(oriented)

    if inferred is not None:
        orf_nt, aa, orf_strand, coding_homology = inferred
        # Two conditions, and the second is not redundant. Containment over a *run* has the
        # run's own k-mer count as its denominator, so a 20-residue run needs only two or three
        # chance matches to clear the floor — see `CodonSpec.noncoding_homology_margin` for the six
        # 5'UTR amplicons that did exactly that, and for why the 5'NCR pool has to win by a margin
        # rather than merely win.
        reads_as_protein = coding_homology >= spec.infer_min_homology and (
            ncr5_homology - coding_homology <= spec.noncoding_homology_margin
        )
        if reads_as_protein:
            orf_nt, aa, unsequenced_nt = _drop_ambiguous_runs(orf_nt, aa, spec)
            if aa:  # see the annotated path above for why this is not assumed away
                return Segmentation(
                    accession=accession,
                    method="inferred",
                    strand=orf_strand,
                    ncr5="",
                    ncr3="",
                    orf_nt=orf_nt,
                    aa=aa,
                    n_internal_stops=0,
                    absence_reason=None,
                    unsequenced_nt=unsequenced_nt,
                )
        reason = ABSENCE_NO_CODING_HOMOLOGY
    else:
        reason = (
            ABSENCE_ANNOTATED_REJECTED_UNTRANSLATABLE
            if cds_features
            else ABSENCE_NO_CDS_UNTRANSLATABLE
        )

    if ncr5_homology < spec.noncoding_min_ncr_homology:
        return Segmentation(
            accession=accession,
            method="none",
            strand="",
            ncr5="",
            ncr3="",
            orf_nt="",
            aa="",
            n_internal_stops=0,
            absence_reason=ABSENCE_NO_CODING_OR_NCR_HOMOLOGY,
        )
    return Segmentation(
        accession=accession,
        method="noncoding",
        strand=strand_used,
        ncr5=oriented,
        ncr3="",
        orf_nt="",
        aa="",
        n_internal_stops=0,
        absence_reason=reason,
    )


def segment_all(
    repository_root: Path,
    records: dict[str, AlignedRecord],
    spec: contract.CodonSpec = _DEFAULT_CODON_SPEC,
) -> tuple[dict[str, Segmentation], HomologyPool]:
    """One `Segmentation` per record in `records`, keyed the same way (base accession), plus the
    pool the inference path was judged against.

    Two passes, and the ordering is the whole point. The first runs with an empty pool, which
    changes nothing on the annotated path — that path never consults homology — and reduces every
    other record to a placeholder nobody reads. The pool is then built from the annotated results
    alone, so the population being judged never votes on itself, and the second pass decides frames
    and coding-versus-not against it. Anything less than two passes would be circular: the reference
    for "reads as enterovirus protein" is the corpus's own accepted annotations.
    """
    cds_by_record, parts_by_feature, codon_starts = _load_cds_index(repository_root)

    def run(pool: HomologyPool) -> dict[str, Segmentation]:
        return {
            accession: segment_one(
                accession,
                record.sequence,
                record.version,
                cds_by_record,
                parts_by_feature,
                codon_starts,
                spec,
                pool,
            )
            for accession, record in records.items()
        }

    pool = build_homology_pool(run(EMPTY_POOL), spec)
    if not pool.protein:
        raise ContractError(
            "no annotated-path record reaches "
            f"infer_pool_min_aa={spec.infer_pool_min_aa} aa, so there is nothing to judge an "
            "inferred reading frame against; refusing to fall back to longest-ORF"
        )
    return run(pool), pool
