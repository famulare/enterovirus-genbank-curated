"""Sequence evidence: the Sabin reference frame, and the distances measured against it.

Every column left pending in this pipeline was pending for the same reason — no stage compared a
record's sequence to a reference. This is that stage, and it needs no aligner binary and no
reference panel from outside the clone, because both inputs are already in `raw/`.

## The reference frame is derivable, not supplied

`AY184219`, `AY184220` and `AY184221` — Sabin 1, 2 and 3 — are in the frozen archive, each carrying
all eleven `mat_peptide` features. Their coordinates reproduce the shipped
`final/alignments/reference_region_coordinates.tsv` exactly for all three serotypes, VP1 included
(2480–3385, 2482–3384, 2477–3376). So the frame is computed here from the same GenBank features
everything else in this pipeline reads, and the shipped coordinate table is a comparison target
rather than an input — boundary 1, unchanged.

The only difference from the shipped table is the last three nucleotides of `3D`, where the table
includes the stop codon and the `mat_peptide` feature does not. Nothing here reads `3D`.

The capsid interval comes from the same features: VP4's start to VP1's end, the four structural
peptides being contiguous. VP4's start also fixes the polyprotein reading frame, and it equals the
`polyprotein` CDS start on all three references (743, 748, 743), so the phase is read off the
`mat_peptide` features rather than joining a second feature key to get it.

## Three distances, because they answer three different questions

`compare_vp1` measures **nucleotide** divergence over VP1, which is what the WHO classification
thresholds are defined on. `compare_capsid_aa` measures **amino-acid** p-distance over the capsid,
which is what membership is decided on, and the difference is not stylistic. Synonymous sites
saturate: a 1980s patent transcription of a Sabin cDNA clone can sit 20% away in nucleotide with its
protein essentially unchanged, and 20% nt is exactly where the `wild` threshold lives. On the
protein those same records sit at 0.2-3%. Nucleotide distance would read them as unrelated;
amino-acid distance reads them as what they are.

`compare_capsid_nt` measures **nucleotide** divergence over the whole capsid (VP4-VP2-VP3-VP1), and
exists only because VP1 alone is absent or too short on 1,911 carved, name-serotyped records — the
same fallback MAD-VDPV's own pipeline takes, stated outright in `classify_sequence_tier.py` as
"VP1-first / P1-fallback". It answers the same question `compare_vp1` does and uses the same
thresholds; it is not a third kind of evidence, just VP1's question asked over more sequence when
VP1 itself is not there to answer it.

## Why k-mer diagonals instead of an alignment

No aligner is installed, and building one would be the wrong risk. What the classification rule
actually needs is a divergence percentage over VP1, and VP1 in poliovirus has no indels relative to
Sabin — so an ungapped comparison at a fixed offset is not an approximation of the answer, it *is*
the answer.

The offset is found by seeding: index every 12-mer of the reference, look up every 12-mer of the
query, and vote on `reference_position - query_position`. The winning diagonal is the offset. This
is the classic seed-and-extend first step, and at k=12 it stays sensitive across the ~20% divergence
that separates wild poliovirus from Sabin, because synonymous-site conservation leaves plenty of
exact 12-mers even there. Measured: it places every one of the 9,600-odd poliovirus records that
carry a serotype in their organism name.

**Both strands are tried.** 42 poliovirus records in the corpus are deposited on the minus strand,
and a forward-only search silently reports them as unmappable — which would then look like a
declined cell rather than a bug.

## What this stage does *not* do, and both are deliberate

**It does not serotype by sequence.** Measured against the release, a best-matching-Sabin call over
VP1 agrees with the shipped `virus_type` on 98.6% of the records it calls — and the 1.4% is not
noise. One Sabin per serotype is a poor stand-in for wild poliovirus, whose VP1 sits ~20% from all
three, so the nearest of the three is partly an accident of which window was deposited. The
organism name already agrees with the release on 99.95% of the rows it resolves (see
`derive/typing.py`), so using the sequence here would replace a better answer with a worse one. The
name picks the reference; the sequence measures the distance to it.

**It does not reconstruct `sequence_scope`.** The geometry needed for that — which reference regions
a record covers — is computable and was computed. It does not reproduce the shipped column: fitted
against every threshold combination, coverage geometry agrees with `record_type` on 86.7% of
poliovirus records, and the errors are systematic rather than at the boundary. 745 records the
release calls `other_fragment` have complete VP1, complete capsid, or a complete genome by coverage.
So `record_type` is not a function of coverage against Sabin VP1 alone, whatever else it is, and
fitting thresholds to 86.7% would assert a wrong determination on 1,332 records.
`sequence_scope` stays in `PENDING_COLUMNS`.

## Why the fallback needs a guard `compare_vp1` did not always need

`compare_vp1` is exact at one fixed offset because VP1 in poliovirus has no indels relative to Sabin
— a measured fact, not an assumption, and this module's own justification for skipping an aligner.
That fact rules out one failure mode (a true evolutionary insertion or deletion) but not another: a
single wrong base call *in the deposited read itself* — a technical artifact of how the sequence was
determined, not biology, and so not excluded by "VP1 has no indels" at all. Reproducing MAD-VDPV's
whole-capsid fallback the same way — one diagonal, no gaps — surfaces sequences where this happens;
lowering `MIN_VP1_NT` far enough surfaces it in VP1 too.

Three carved, name-serotyped records where the naive whole-capsid measurement disagreed with the
release diagnosed exactly why. `AB162760.1` and `AB162761.1` read >18 percentage points more
divergent than MAD-VDPV's own alignment reports for the same accessions (9.8-10.1% vs 0.0-0.2%),
and in both the mismatches begin at one exact position and run at ~74-90% (the unrelated-sequence
rate) for the rest of the window. Shifting the query by **one nucleotide** from that position on
restores 98-100% identity. A real indel in a coding, actively-replicating poliovirus genome must be
a multiple of three to preserve the reading frame — a 1-nt shift is not biology, it is a single bad
base call in the GenBank deposit, and the single fixed diagonal has no way to know the rest of the
window sits on the wrong side of it.

At the original 300 nt VP1 floor this class of error was apparently rare enough never to surface: a
~900 nt region with, evidently, an occasional bad base in the corpus, and 300 nt of it was enough
sequence to dilute one bad call rather than be defined by it. Lowering `MIN_VP1_NT` to 50 nt (to
match MAD-VDPV's own floor, 2026-07-31) removed that dilution, and it surfaced exactly this failure
in VP1 for the first time — `AY320423`, `JN092124` and `AY365233` each read 15-24 percentage points
more divergent than MAD-VDPV's own alignment over a 171-225 nt window. The same mechanism, now in
the region this module's own no-indels argument does not protect.

So the fallback needs to detect a window that is not internally consistent, not just decline a
window that is too short — and now that `MIN_VP1_NT` reaches below 300 nt too, `compare_vp1` needs
the same check `compare_capsid_nt` does, for windows short enough that the old floor no longer
protects them by dilution alone.

`_capsid_homogeneous` is that check: split the compared span into 150 nt chunks, and require every
chunk with at least 30 compared positions to sit within `MAX_CAPSID_CHUNK_DEVIATION_PCT` of the
whole window's own divergence — and require at least `MIN_HOMOGENEITY_CHUNKS` such chunks, because a
single chunk trivially "agrees with itself" and a window that short has nothing to check internal
consistency against. Measured over every record that gets any capsid-nt measurement at the original
300 nt floor: the three genuinely bad windows sit at 21.5, 21.8 and 55.2 percentage points of
internal deviation; the next-highest clean one sits at 8.1. That gap, not a fitted number, is where
`MAX_CAPSID_CHUNK_DEVIATION_PCT` is set, and it is shared by both `compare_vp1` (below 300 nt) and
`compare_capsid_nt` (always) rather than fitted separately for each.

`compare_vp1` applies this guard only below `VP1_HOMOGENEITY_FLOOR_NT` (300 nt, the old floor): at or
above it, behavior is unchanged from before the floor was lowered, so none of the measurements this
stage already shipped are put at risk by a check built to catch a failure discovered afterward.
"""

from __future__ import annotations

import collections
from collections.abc import Mapping
from dataclasses import dataclass

from enterovirus_genbank_curated.derive.metadata import ENTEROVIRUS_GENUS_TAXON

SABIN_REFERENCES = {"PV1": "AY184219.1", "PV2": "AY184220.1", "PV3": "AY184221.1"}
VP1_PRODUCT = "VP1"
VP4_PRODUCT = "VP4"
MAT_PEPTIDE = "mat_peptide"
PRODUCT_QUALIFIER = "product"

# Seed length. Long enough that a 12-mer is rarely shared by chance across 7.4 kb (4^12 = 16.8M
# possibilities against ~7,400 positions), short enough to survive ~20% divergence.
SEED = 12
# MAD-VDPV's own floor (`build_reference_alignments.MIN_SEROTYPE_COMPARED_NT`), adopted 2026-07-31.
# It is safe to match exactly, and not merely close, because it rests on a fact specific to VP1: VP1
# in poliovirus has no indels relative to Sabin (the module docstring's own justification for a
# single fixed diagonal at any length), so a shorter window is a smaller sample of the same exact
# measurement, never a different one. Cross-serotype VP1 divergence (~31-37%) vs homotypic (~0-25%)
# means even 50 nt picks the right serotype with a clear gap, which is `classify_sequence_tier.py`'s
# own reasoning for the number.
MIN_VP1_NT = 50
# Anchors the winning diagonal must carry. Without a floor, a record that does not overlap VP1 at
# all still wins some diagonal on one chance 12-mer, and the resulting comparison reports ~74%
# divergence — the value for unrelated sequence — which then reads as `wild`. Measured: 73 records
# the release calls `Sabin-like` were being called `wild` this way, all of them at 73-74%. A genuine
# match over 300 nt at under 20% divergence carries dozens of exact 12-mers, so 5 is a low bar that
# nonetheless excludes every chance hit.
MIN_DIAGONAL_ANCHORS = 5
# Above this the two sequences are not homologous over the compared window and no alignment is
# being measured. Enterovirus VP1 across *genera* stays well below it; 74% is the unrelated-sequence
# expectation. A result this far out is reported as no measurement rather than as a large number.
IMPLAUSIBLE_DIVERGENCE_PCT = 40.0

# Same floor as `MIN_VP1_NT`, matching MAD-VDPV's own `MIN_SEROTYPE_COMPARED_NT`, adopted 2026-07-31
# — but unlike VP1, this is a fallback over VP4/VP2/VP3 too, and those regions are not established
# indel-free the way VP1 is, so the floor alone is not the safety argument here; the strengthened
# `_capsid_homogeneous` below is.
MIN_CAPSID_NT = 50
# Chunk size for the homogeneity check below. Large enough that 5 exact 12-mer anchors are ordinary
# within a genuine match (the same anchor floor `_best_diagonal` already applies over the whole
# window), small enough to localize a single bad base rather than average it into the whole capsid.
CAPSID_HOMOGENEITY_CHUNK_NT = 150
# A chunk shorter than this is too small a sample to judge on its own; it is folded into the overall
# count but not held to the deviation floor below.
MIN_HOMOGENEITY_CHUNK_NT = 30
# At the original 300 nt floor this was implicit: 300 nt is always at least two 150 nt chunks, so the
# homogeneity check always had two independent samples to compare against each other. Lowering the
# floor to 50 nt breaks that — a 50-179 nt window is a *single* chunk, which trivially "agrees with
# itself" and would pass with no check at all. Below `MIN_HOMOGENEITY_CHUNKS`, `_capsid_homogeneous`
# declines rather than rubber-stamps: it has nothing to check internal consistency against. This adds
# no restriction anywhere the 300 nt floor already reached — every record that passed before had at
# least two qualifying chunks already — so it only governs the newly-opened 50-299 nt territory.
MIN_HOMOGENEITY_CHUNKS = 2
# Measured, not fitted: over every record that reaches any capsid-nt measurement, the three windows
# a single bad base call breaks sit at 21.5, 21.8 and 55.2 percentage points of chunk-to-window
# deviation; the next-highest genuine window sits at 8.1. The threshold sits in that gap.
MAX_CAPSID_CHUNK_DEVIATION_PCT = 15.0

ACGT = frozenset("ACGT")

_COMPLEMENT = str.maketrans("ACGTacgtNn", "TGCAtgcaNn")

# The standard genetic code, for translating the polyprotein reading frame. A codon containing an
# ambiguity character is absent here and is skipped rather than guessed at, so an `N` reduces the
# number of codons compared instead of counting as a difference.
CODON_TABLE = {
    "TTT": "F", "TTC": "F", "TTA": "L", "TTG": "L",
    "CTT": "L", "CTC": "L", "CTA": "L", "CTG": "L",
    "ATT": "I", "ATC": "I", "ATA": "I", "ATG": "M",
    "GTT": "V", "GTC": "V", "GTA": "V", "GTG": "V",
    "TCT": "S", "TCC": "S", "TCA": "S", "TCG": "S",
    "CCT": "P", "CCC": "P", "CCA": "P", "CCG": "P",
    "ACT": "T", "ACC": "T", "ACA": "T", "ACG": "T",
    "GCT": "A", "GCC": "A", "GCA": "A", "GCG": "A",
    "TAT": "Y", "TAC": "Y", "TAA": "*", "TAG": "*",
    "CAT": "H", "CAC": "H", "CAA": "Q", "CAG": "Q",
    "AAT": "N", "AAC": "N", "AAA": "K", "AAG": "K",
    "GAT": "D", "GAC": "D", "GAA": "E", "GAG": "E",
    "TGT": "C", "TGC": "C", "TGA": "*", "TGG": "W",
    "CGT": "R", "CGC": "R", "CGA": "R", "CGG": "R",
    "AGT": "S", "AGC": "S", "AGA": "R", "AGG": "R",
    "GGT": "G", "GGC": "G", "GGA": "G", "GGG": "G",
}


def reverse_complement(sequence: str) -> str:
    return sequence.translate(_COMPLEMENT)[::-1]


@dataclass(frozen=True)
class ReferenceFrame:
    """One Sabin reference: its sequence, its VP1 and capsid intervals, and its seed index."""

    serotype: str
    version: str
    sequence: str
    vp1_start: int  # 0-based, inclusive
    vp1_end: int  # 0-based, exclusive
    capsid_start: int  # 0-based, inclusive; VP4 start, which is also the polyprotein CDS start
    index: Mapping[str, tuple[int, ...]]

    @property
    def vp1_length(self) -> int:
        return self.vp1_end - self.vp1_start

    @property
    def capsid_end(self) -> int:
        """The capsid is VP4-VP2-VP3-VP1 contiguously, so it ends where VP1 does."""
        return self.vp1_end


def _seed_index(sequence: str) -> dict[str, tuple[int, ...]]:
    positions: dict[str, list[int]] = {}
    for offset in range(len(sequence) - SEED + 1):
        positions.setdefault(sequence[offset : offset + SEED], []).append(offset)
    return {seed: tuple(found) for seed, found in positions.items()}


def build_reference_frames(
    tables: Mapping[str, list[dict[str, str]]], sequences: Mapping[str, str]
) -> dict[str, ReferenceFrame]:
    """The three Sabin frames, with VP1 taken from each record's own `mat_peptide` features.

    Raises if a reference or its VP1 feature is absent, rather than proceeding with two frames: a
    silently missing serotype would make every record of that serotype decline, which reads as a
    data gap rather than as the broken input it is.
    """
    record_id = {row["version"]: row["record_id"] for row in tables["records"]}
    features_by_record: dict[str, list[str]] = {}
    feature_key = {}
    for row in tables["features"]:
        feature_key[row["feature_id"]] = row["feature_key"]
        features_by_record.setdefault(row["record_id"], []).append(row["feature_id"])
    product: dict[str, str] = {}
    for row in tables["feature_qualifiers"]:
        if row["qualifier_name"] == PRODUCT_QUALIFIER:
            product.setdefault(row["feature_id"], row["qualifier_value"])
    span: dict[str, tuple[int, int]] = {}
    for row in tables["feature_location_parts"]:
        start, end = int(row["start_1based"]), int(row["end_1based_inclusive"])
        if row["feature_id"] in span:
            known = span[row["feature_id"]]
            span[row["feature_id"]] = (min(known[0], start), max(known[1], end))
        else:
            span[row["feature_id"]] = (start, end)

    frames: dict[str, ReferenceFrame] = {}
    for serotype, version in SABIN_REFERENCES.items():
        if version not in record_id or version not in sequences:
            raise ValueError(f"{serotype} reference {version} is not in the corpus")
        sequence = sequences[version].upper()
        peptides = {
            product.get(feature_id, "").strip(): span[feature_id]
            for feature_id in features_by_record.get(record_id[version], ())
            if feature_key.get(feature_id) == MAT_PEPTIDE
        }
        vp1 = [interval for name, interval in peptides.items() if name.endswith(VP1_PRODUCT)]
        vp4 = [interval for name, interval in peptides.items() if name.endswith(VP4_PRODUCT)]
        if len(vp1) != 1:
            raise ValueError(
                f"{version} carries {len(vp1)} VP1 mat_peptide features, not exactly one; the "
                f"reference frame cannot be derived from it"
            )
        if len(vp4) != 1:
            raise ValueError(
                f"{version} carries {len(vp4)} VP4 mat_peptide features, not exactly one; the "
                f"capsid reading frame cannot be derived from it"
            )
        start, end = vp1[0]
        # VP4 begins the polyprotein, so its start is both the capsid start and the reading frame's
        # phase. Measured against the three references: VP4's start equals the `polyprotein` CDS
        # start in all three (743, 748, 743), so this reads the frame off the same features the VP1
        # interval comes from rather than joining a second feature key to get it.
        capsid_start = vp4[0][0]
        frames[serotype] = ReferenceFrame(
            serotype=serotype,
            version=version,
            sequence=sequence,
            vp1_start=start - 1,
            vp1_end=end,
            capsid_start=capsid_start - 1,
            index=_seed_index(sequence),
        )
    return frames


def _best_diagonal(frame: ReferenceFrame, candidate: str, lo: int, hi: int) -> int | None:
    """The offset with most exact-seed support inside `[lo, hi)`, or None below the anchor floor."""
    votes: collections.Counter[int] = collections.Counter()
    for offset in range(max(0, len(candidate) - SEED + 1)):
        for found in frame.index.get(candidate[offset : offset + SEED], ()):
            if lo <= found < hi:
                votes[found - offset] += 1
    if not votes:
        return None
    diagonal, anchors = votes.most_common(1)[0]
    return diagonal if anchors >= MIN_DIAGONAL_ANCHORS else None


@dataclass(frozen=True)
class Vp1Comparison:
    """VP1 divergence of one record from one Sabin reference."""

    serotype: str
    reference_version: str
    divergence_pct: float
    compared_nt: int
    strand: str


# Below this, `compare_vp1` holds itself to the same chunked-homogeneity check `compare_capsid_nt`
# always needed. At or above it, behavior is exactly what it was before `MIN_VP1_NT` was lowered to
# 50 (a bare mismatch count, no chunking) — the 7,728 VP1 comparisons this stage already ships are
# untouched. The reason the two regions need different treatment is JN092124/AY320423/AY365233
# (2026-07-31): three records where lowering the floor to 50 nt let a single bad base call in the
# deposit (not a real indel — VP1 has none relative to Sabin, but a technical artifact of the read
# can land anywhere) corrupt a 171-225 nt window the same way `_capsid_homogeneous`'s own module
# docstring already diagnoses for the capsid case, each landing at 20-34% where MAD-VDPV's own
# alignment reports 6-11%. A short window is not exempt from the failure that guard exists for; it
# was only ever *untested* below 300 nt, because nothing shorter used to reach this far.
VP1_HOMOGENEITY_FLOOR_NT = 300


def compare_vp1(frame: ReferenceFrame, sequence: str) -> Vp1Comparison | None:
    """Ungapped VP1 divergence at the best-supported offset, or None below `MIN_VP1_NT`.

    Anchors are restricted to VP1 before the vote. Using a genome-wide offset would let a
    recombinant's non-capsid region choose the diagonal, and in poliovirus that region routinely
    comes from a different serotype than the capsid does.
    """
    best: Vp1Comparison | None = None
    for strand, candidate in (("+", sequence.upper()), ("-", reverse_complement(sequence.upper()))):
        diagonal = _best_diagonal(frame, candidate, frame.vp1_start, frame.vp1_end)
        if diagonal is None:
            continue
        first = max(frame.vp1_start, diagonal)
        last = min(frame.vp1_end, len(frame.sequence), len(candidate) + diagonal)
        compared = last - first
        if compared < MIN_VP1_NT or (best is not None and compared <= best.compared_nt):
            continue
        mismatches = 0
        chunk_divergences: list[float] = []
        for chunk_start in range(first, last, CAPSID_HOMOGENEITY_CHUNK_NT):
            chunk_end = min(chunk_start + CAPSID_HOMOGENEITY_CHUNK_NT, last)
            chunk_mismatches = sum(
                1
                for position in range(chunk_start, chunk_end)
                if candidate[position - diagonal] != frame.sequence[position]
            )
            mismatches += chunk_mismatches
            chunk_length = chunk_end - chunk_start
            if chunk_length >= MIN_HOMOGENEITY_CHUNK_NT:
                chunk_divergences.append(chunk_mismatches / chunk_length * 100)
        divergence = mismatches / compared * 100
        if divergence > IMPLAUSIBLE_DIVERGENCE_PCT:
            continue
        if compared < VP1_HOMOGENEITY_FLOOR_NT and not _capsid_homogeneous(
            chunk_divergences, divergence
        ):
            continue
        best = Vp1Comparison(
            serotype=frame.serotype,
            reference_version=frame.version,
            divergence_pct=divergence,
            compared_nt=compared,
            strand=strand,
        )
    return best


@dataclass(frozen=True)
class CapsidNtComparison:
    """Whole-capsid (P1) nucleotide divergence of one record from one Sabin reference.

    Used only as a fallback when `compare_vp1` returns `None`. Answers the same question VP1
    divergence does — how far this record's Sabin-facing region has diverged — over more sequence,
    which is both why it can reach records VP1 cannot and why it needs `_capsid_homogeneous`: more
    sequence is more chances for one bad base call to sit inside the window.
    """

    serotype: str
    reference_version: str
    divergence_pct: float
    compared_nt: int
    strand: str


def _capsid_homogeneous(chunk_divergences: list[float], whole_window_pct: float) -> bool:
    """Every sampled chunk within `MAX_CAPSID_CHUNK_DEVIATION_PCT` of the whole window's rate.

    A window that fails this is not "more diverged" — see the module docstring for the two cases
    that motivated it, where a single bad base call in the deposit put everything downstream of it
    at the unrelated-sequence rate while everything before it read at zero. Declining is not this
    function guessing which side is right; it is refusing to average two things that are not the
    same measurement into one number.

    Fewer than `MIN_HOMOGENEITY_CHUNKS` qualifying chunks is declined outright, not passed: a single
    chunk trivially "deviates" from itself by zero, so below two chunks this check has nothing to
    compare and would otherwise rubber-stamp the one case it cannot see inside — a short window with
    one bad base call spread over too little sequence to localize it.
    """
    if len(chunk_divergences) < MIN_HOMOGENEITY_CHUNKS:
        return False
    return all(
        abs(chunk - whole_window_pct) <= MAX_CAPSID_CHUNK_DEVIATION_PCT
        for chunk in chunk_divergences
    )


def compare_capsid_nt(frame: ReferenceFrame, sequence: str) -> CapsidNtComparison | None:
    """Ungapped capsid divergence at the best-supported offset, or `None` below the guards.

    Raw-ACGT p-distance, matching the definition the fallback exists to reproduce: a position counts
    only when both the reference and the query base are unambiguous. `compare_vp1` does not filter
    this way — measured, it would move 315 of the 7,728 shipped VP1 comparisons, an existing,
    validated computation this change has no reason to touch. This function has no such history to
    preserve, and matching the source method's own definition is the more defensible default for it.
    """
    best: CapsidNtComparison | None = None
    for strand, candidate in (("+", sequence.upper()), ("-", reverse_complement(sequence.upper()))):
        diagonal = _best_diagonal(frame, candidate, frame.capsid_start, frame.capsid_end)
        if diagonal is None:
            continue
        first = max(frame.capsid_start, diagonal)
        last = min(frame.capsid_end, len(frame.sequence), len(candidate) + diagonal)
        compared = mismatches = 0
        chunk_divergences: list[float] = []
        for chunk_start in range(first, last, CAPSID_HOMOGENEITY_CHUNK_NT):
            chunk_end = min(chunk_start + CAPSID_HOMOGENEITY_CHUNK_NT, last)
            chunk_compared = chunk_mismatches = 0
            for position in range(chunk_start, chunk_end):
                reference_base = frame.sequence[position]
                query_base = candidate[position - diagonal]
                if reference_base in ACGT and query_base in ACGT:
                    chunk_compared += 1
                    chunk_mismatches += reference_base != query_base
            compared += chunk_compared
            mismatches += chunk_mismatches
            if chunk_compared >= MIN_HOMOGENEITY_CHUNK_NT:
                chunk_divergences.append(chunk_mismatches / chunk_compared * 100)
        if compared < MIN_CAPSID_NT or (best is not None and compared <= best.compared_nt):
            continue
        divergence = mismatches / compared * 100
        if divergence > IMPLAUSIBLE_DIVERGENCE_PCT:
            continue
        if not _capsid_homogeneous(chunk_divergences, divergence):
            continue
        best = CapsidNtComparison(
            serotype=frame.serotype,
            reference_version=frame.version,
            divergence_pct=divergence,
            compared_nt=compared,
            strand=strand,
        )
    return best


@dataclass(frozen=True)
class CapsidComparison:
    """Capsid amino-acid p-distance of one record from one Sabin reference."""

    serotype: str
    reference_version: str
    distance_pct: float
    compared_codons: int
    strand: str


def compare_capsid_aa(frame: ReferenceFrame, sequence: str) -> CapsidComparison | None:
    """Amino-acid p-distance over the capsid, translated in the reference's own reading frame.

    Amino acids rather than nucleotides, because this is a *membership* question and not a distance
    within poliovirus. Synonymous sites saturate: a patent-era cDNA clone re-transcribed with a
    different codon bias can sit 20% away in nucleotide while its protein is unchanged, and 20% nt
    is exactly where the wild threshold lives. The protein keeps the signal where the third position
    has stopped carrying one.

    The reading frame is the reference's, taken from `capsid_start`, so both codons are read in the
    same phase and no frame has to be guessed for the query. Codons containing an ambiguity
    character are skipped by `CODON_TABLE`, which shrinks the denominator rather than inventing a
    difference.
    """
    best: CapsidComparison | None = None
    for strand, candidate in (("+", sequence.upper()), ("-", reverse_complement(sequence.upper()))):
        diagonal = _best_diagonal(frame, candidate, frame.capsid_start, frame.capsid_end)
        if diagonal is None:
            continue
        first = max(frame.capsid_start, diagonal)
        last = min(frame.capsid_end, len(frame.sequence), len(candidate) + diagonal)
        # Advance to the next codon boundary *of the reference frame*, so position `first` is read
        # in the same phase the polyprotein is translated in.
        start = first + (-(first - frame.capsid_start)) % 3
        same = compared = 0
        for position in range(start, last - 2, 3):
            reference_aa = CODON_TABLE.get(frame.sequence[position : position + 3])
            query_aa = CODON_TABLE.get(candidate[position - diagonal : position - diagonal + 3])
            if reference_aa is None or query_aa is None:
                continue
            compared += 1
            same += reference_aa == query_aa
        if compared == 0:
            continue
        distance = (compared - same) / compared * 100
        if distance > IMPLAUSIBLE_DIVERGENCE_PCT:
            continue
        # Nearest reference wins, and the tie-break is codon count. Ordering by codon count first
        # picked the *wrong* serotype on E00768: PV1 covered 371 codons at 22.9% and PV2 covered 370
        # at 0.81%, so one extra codon outranked a 22-point difference in distance.
        if best is None or (distance, -compared) < (best.distance_pct, -best.compared_codons):
            best = CapsidComparison(
                serotype=frame.serotype,
                reference_version=frame.version,
                distance_pct=distance,
                compared_codons=compared,
                strand=strand,
            )
    return best


MEMBERSHIP_BY_BYTES = "byte_identical_to_a_carved_enterovirus_record"
MEMBERSHIP_BY_CAPSID_AA = "capsid_aa_distance_below_rescue_threshold"

MEMBERSHIP_COLUMNS = (
    "accession",
    "version",
    "organism_name",
    "membership_basis",
    "reference_serotype",
    "reference_version",
    "capsid_aa_distance_pct",
    "capsid_codons_compared",
    "byte_identical_twin",
)


@dataclass(frozen=True)
class MembershipRescue:
    """Why one record outside the Enterovirus lineage nonetheless belongs in the carve."""

    version: str
    basis: str
    reference_serotype: str = ""
    reference_version: str = ""
    distance_pct: str = ""
    compared_codons: str = ""
    twin_version: str = ""


def measure_membership_rescue(
    tables: Mapping[str, list[dict[str, str]]],
    sequences: Mapping[str, str],
    excluded_accessions: frozenset[str],
    parameters: Mapping[str, str],
) -> dict[str, MembershipRescue]:
    """R-MEMBERSHIP-AA-1 over every record the lineage predicate rejects.

    Two bases, checked in that order because the first is exact and the second is a measurement:

    1. **Byte identity.** A record whose sequence digest matches a record the lineage predicate
       accepts is the same sequence, and membership is a property of the sequence. This needs no
       threshold. It is also the only basis that reaches the five 70-nt patent oligos, which do not
       overlap the capsid at all and so have no amino-acid distance to measure.
    2. **Capsid amino-acid p-distance** below the catalog's `rescue_below_pct` over at least
       `min_codons_compared` codons.

    Scoped to the records the lineage predicate *rejects*, so this can only ever add rows. A record
    the ledger actively excludes is not reconsidered: an exclusion decision is a curator overriding
    the sequence, and re-including it here would silently reverse them.
    """
    rescue_below = float(parameters["rescue_below_pct"])
    min_codons = int(parameters["min_codons_compared"])

    lineage = {}
    for row in tables["record_taxonomy"]:
        lineage.setdefault(row["record_id"], set()).add(row["taxon_name"])

    carved: set[str] = set()
    candidates: list[dict[str, str]] = []
    for record in tables["records"]:
        if record["accession"] in excluded_accessions:
            continue
        if ENTEROVIRUS_GENUS_TAXON in lineage.get(record["record_id"], set()):
            carved.add(record["sequence_sha256"])
        else:
            candidates.append(record)

    twin_of: dict[str, str] = {}
    for record in tables["records"]:
        if record["accession"] in excluded_accessions:
            continue
        if ENTEROVIRUS_GENUS_TAXON in lineage.get(record["record_id"], set()):
            twin_of.setdefault(record["sequence_sha256"], record["version"])

    frames = build_reference_frames(tables, sequences)
    rescued: dict[str, MembershipRescue] = {}
    for record in candidates:
        version = record["version"]
        if record["sequence_sha256"] in carved:
            rescued[version] = MembershipRescue(
                version=version,
                basis=MEMBERSHIP_BY_BYTES,
                twin_version=twin_of[record["sequence_sha256"]],
            )
            continue
        sequence = sequences.get(version)
        if sequence is None:
            continue
        calls = [
            call
            for call in (compare_capsid_aa(frame, sequence) for frame in frames.values())
            if call
        ]
        if not calls:
            continue
        best = min(calls, key=lambda call: (call.distance_pct, -call.compared_codons))
        if best.compared_codons < min_codons or best.distance_pct >= rescue_below:
            continue
        rescued[version] = MembershipRescue(
            version=version,
            basis=MEMBERSHIP_BY_CAPSID_AA,
            reference_serotype=best.serotype,
            reference_version=best.reference_version,
            distance_pct=f"{best.distance_pct:.3f}",
            compared_codons=str(best.compared_codons),
        )
    return rescued


# The schema of `audit/classification_divergence.tsv.gz`, which
# `export/audit.write_classification_divergence` writes. Basis-neutral names (`divergence_pct`, not
# `vp1_divergence_pct`), because a row's `basis` column is `VP1` on most rows and `P1_capsid` on the
# fallback ones, and a column named for one basis while carrying values from another would mislead
# a reader who skips the `basis` column. Deliberately not the shipped `final/audit/
# sequence_evidence.tsv.gz` schema, and the choice of name is argued where the name is chosen.
EVIDENCE_COLUMNS = (
    "accession",
    "version",
    "reference_serotype",
    "reference_version",
    "divergence_pct",
    "compared_nt",
    "strand",
    "basis",
)

BASIS_VP1 = "VP1"
BASIS_CAPSID = "P1_capsid"


def measure_sequence_evidence(
    tables: Mapping[str, list[dict[str, str]]],
    sequences: Mapping[str, str],
    rows: list[dict[str, str]],
) -> dict[str, dict[str, str]]:
    """VP1-first, capsid-fallback divergence for every carved record whose organism name names a
    serotype — the same precedence MAD-VDPV's own `classify_sequence_tier.py` states outright:
    "VP1-first / P1-fallback".

    Scoped to name-serotyped records on purpose. The organism name is what picks the reference —
    this stage does not serotype by sequence, for the reason the module docstring gives — so a
    record with no name serotype has nothing to be measured *against*, and measuring it against all
    three would be inventing the very call that was declined.

    The fallback is tried only when VP1 itself returns nothing, never to override a VP1 measurement
    that exists: VP1 is the region the WHO thresholds are defined on, and a longer, guarded
    comparison over more sequence is a fallback for VP1's absence, not a better version of it.
    """
    from enterovirus_genbank_curated.derive.typing import serotype_from_name

    frames = build_reference_frames(tables, sequences)
    measured: dict[str, dict[str, str]] = {}
    for row in rows:
        serotype = serotype_from_name(row.get("organism_name", ""))
        frame = frames.get(serotype)
        if frame is None:
            continue
        sequence = sequences.get(row["version"])
        if sequence is None:
            continue
        vp1 = compare_vp1(frame, sequence)
        if vp1 is not None:
            measured[row["version"]] = {
                "reference_serotype": vp1.serotype,
                "reference_version": vp1.reference_version,
                # Three decimals, so 1/903 nt reads as 0.111 rather than as a float repr that
                # differs across platforms. The threshold comparison is done on `Decimal` of this
                # string, so the number the rule decided on is exactly the number cited.
                "divergence_pct": f"{vp1.divergence_pct:.3f}",
                "compared_nt": str(vp1.compared_nt),
                "strand": vp1.strand,
                "basis": BASIS_VP1,
            }
            continue
        capsid = compare_capsid_nt(frame, sequence)
        if capsid is None:
            continue
        measured[row["version"]] = {
            "reference_serotype": capsid.serotype,
            "reference_version": capsid.reference_version,
            "divergence_pct": f"{capsid.divergence_pct:.3f}",
            "compared_nt": str(capsid.compared_nt),
            "strand": capsid.strand,
            "basis": BASIS_CAPSID,
        }
    return measured
