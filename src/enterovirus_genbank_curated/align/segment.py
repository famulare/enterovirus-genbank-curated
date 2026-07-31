"""One segmentation pass over every canonical record: the primary CDS split into 5'NCR / ORF /
3'NCR, or a 6-frame inference fallback when no CDS is annotated at all.

Ported from MAD-VDPV's `build_ev_segmentation.py` (`build_polio_segmentation.py` re-used its logic
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

_DEFAULT_CODON_SPEC = contract.CodonSpec()

_COMPLEMENT = str.maketrans("ACGTN", "TGCAN")
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
    """One record's segmentation result. `ncr5`/`ncr3` are only ever populated on the annotated
    path — an inferred frame's boundaries are not trustworthy, so it carries no NCR at all."""

    accession: str
    method: Literal["annotated", "inferred", "none"]
    strand: Literal["+", "-", ""]
    ncr5: str
    ncr3: str
    orf_nt: str
    aa: str
    n_internal_stops: int
    absence_reason: str | None


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


# --- the 6-frame inference fallback, ported verbatim from upstream's `inferred_orf` --------------


def _longest_orf(oriented: str) -> tuple[int, str, str] | None:
    """Longest stop-free ORF across the 3 forward frames of `oriented`.

    Splits each frame's translation at stop codons and keeps the longest segment, so a
    end-to-end translation of a frame that happens to contain no stop by chance does not win
    on raw length over the true polyprotein segment.
    """
    best: tuple[int, str, str] | None = None
    for frame in range(3):
        aa_full = translate(oriented[frame:])
        position = 0
        for segment in aa_full.split("*"):
            if segment:
                nt0 = frame + position * 3
                nt1 = frame + (position + len(segment)) * 3
                candidate = (len(segment), oriented[nt0:nt1], segment)
                if best is None or candidate[0] > best[0]:
                    best = candidate
            position += len(segment) + 1
    return best


def _inferred_orf(sequence: str, spec: contract.CodonSpec) -> tuple[str, str, str] | None:
    """6-frame longest-ORF inference. Returns (orf_nt, aa, strand) with no NCR — the boundaries
    are not trustworthy. `None` if nothing translatable, or too X-heavy to be usable."""
    best: tuple[int, str, str, str] | None = None
    for oriented, strand in ((sequence, "+"), (_revcomp(sequence), "-")):
        found = _longest_orf(oriented)
        if found is None:
            continue
        length, orf_nt, aa = found
        if best is None or length > best[0]:
            best = (length, orf_nt, aa, strand)
    if best is None:
        return None
    _length, orf_nt, aa, strand = best
    if len(aa) < spec.infer_min_aa or aa.count("X") / len(aa) > spec.infer_max_x_fraction:
        return None
    return orf_nt, aa, strand


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
        )

    inferred = _inferred_orf(sequence, spec)
    if inferred is not None:
        orf_nt, aa, strand_used = inferred
        return Segmentation(
            accession=accession,
            method="inferred",
            strand=strand_used,
            ncr5="",
            ncr3="",
            orf_nt=orf_nt,
            aa=aa,
            n_internal_stops=0,
            absence_reason=None,
        )

    reason = (
        ABSENCE_ANNOTATED_REJECTED_UNTRANSLATABLE if cds_features else ABSENCE_NO_CDS_UNTRANSLATABLE
    )
    return Segmentation(
        accession=accession,
        method="none",
        strand="",
        ncr5="",
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
) -> dict[str, Segmentation]:
    """One `Segmentation` per record in `records`, keyed the same way (base accession)."""
    cds_by_record, parts_by_feature, codon_starts = _load_cds_index(repository_root)
    return {
        accession: segment_one(
            accession,
            record.sequence,
            record.version,
            cds_by_record,
            parts_by_feature,
            codon_starts,
            spec,
        )
        for accession, record in records.items()
    }
