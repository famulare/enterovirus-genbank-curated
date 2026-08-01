"""Every input path, column name and alignment parameter, declared exactly once.

This is the `site/pipeline/contract.py` analogue for the alignment layer, and it inherits that
module's rule verbatim: **no other module under `align/` may hardcode a path into `final/`, a
canonical column name, or a numeric parameter.**

## Why this module names no `final/` path itself

`align/` reads `final/canonical/`, `final/audit/` and `final/source/` because the pipeline stages
that would produce those tables natively — `derive`, `curate`, and an eventual alignment-specific
stage — do not exist yet. That is the same justification `oracle/` has for reading `final/`, and it
is why `align/` sits outside `tests/test_module_boundaries.py`'s build-tree list rather than needing
an exemption inside it.

But the reason to read `final/` is not a license to *redeclare* it. Every path below is imported
from `oracle.parity`, which already owns `SHIPPED_CANONICAL_METADATA` and gains the
alignment-specific paths alongside it — so a canonical metadata path bug is one constant to fix,
not two definitions that can drift apart. `test_align_contract_names_no_final_path_itself` (in
`tests/test_module_boundaries.py`) pins this as a rule rather than a convention: this file's own
source text must not contain the string `final/`.

## Population membership is curated, not evidence-gated

The single inversion that makes the rebuilt alignments 1-to-1 with final metadata: upstream tied
*membership* to evidence confidence (`serotype_assignable`, `enterovirus_type_scope`), so any record
its typing could not resolve confidently was simply absent. Here membership comes from curated
`virus_group` / `virus_type`, and evidence is used **only** to assign the seed/backbone/addon tier.

## Re-anchored to 4.0.0 on 2026-08-01

Every path below still reads `final/`, and `final/` is now this pipeline's own release rather than
2.4.1. Nothing in this module changed to make that happen — the paths were always declared once,
and the tree under them moved — but the populations did:

| artifact | 2.4.1 | 4.0.0 | why |
|---|---|---|---|
| `EV_unified` | 24,301 | 24,308 | the carve: +9 `UNDECLARED_EXCLUSIONS`, −2 rescued |
| `POLIO_unified` | 10,084 | 10,090 | +6, short patent deposits the ledger calls poliovirus |
| `NPEV_unified` | 14,217 | 14,218 | +1, `AF326751.2` |
| `PV1_unified` | 4,427 | 4,337 | `virus_type` is now R-TYPE-2's name-derived |
| `PV2_unified` | 3,939 | 3,790 | column, which declines where 2.4.1 asserted a |
| `PV3_unified` | 1,693 | 1,597 | serotype from curated data this repo lacks |

The serotype files are the consequential row. **366 poliovirus records now carry a blank
`virus_type`, against 25 before**, so they are members of `POLIO_unified` and `EV_unified` and of no
`PV{n}` file. That is the same curator decision recorded below applied to a larger population, not
a new one: canonical `virus_type` governs the alignment population *including its blanks*, and
R-TYPE-2 declines rather than guessing a serotype an organism name does not state. 92 of the 366 are
≥3,000 nt, so this is not only short fragments — a full-length record whose deposit names no
serotype is a record this pipeline will not type, and the serotype alignments are correspondingly
smaller and better-evidenced than the shipped ones.

The tier predicate did **not** re-anchor, and could not: see
`population.assert_evidence_covers_the_carve`.

## Curator decision, settled 2026-07-30 — do not re-litigate

Canonical `virus_type` governs the alignment population, **including its blanks**. Mike confirmed
these are decisions already made. That discharges the `docs/pipeline.md` "record membership or
scientific values change unexpectedly" stop condition for three consequences of rebuilding:

- the 32 PV serotype relabels (31 records to PV3, 1 PV2 to PV1) relative to the shipped `PV{n}`
  files. The evidence agrees with canonical: 40 of the 43 affected records have fewer than 100
  capsid codons compared (mean 58.3), so the coverage-guarded serotype rule rejects the
  sequence-based capsid call as under-powered and falls back to the submitted GenBank name.
  `OR538733`, which upstream hand-adjudicated with a p-distance guard bypass, is included;
- the 25 blank-`virus_type` poliovirus records, which are members of POLIO and EV and of no
  `PV{n}`;
- the 11 records that lose `virus_type` relative to the shipped `PV{n}` files.

Adjudicated is not invisible. These rows still ship in the per-artifact drop table with a reason
apiece, and the shape report still counts them. The decision means they do not *block*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from enterovirus_genbank_curated.align.seeds import SEED_DIR
from enterovirus_genbank_curated.oracle.parity import (
    SHIPPED_CANONICAL_FASTA,
    SHIPPED_CANONICAL_METADATA,
    SHIPPED_SEQUENCE_EVIDENCE,
    SHIPPED_SOURCE_FEATURE_PARTS,
    SHIPPED_SOURCE_FEATURE_QUALIFIERS,
    SHIPPED_SOURCE_FEATURES,
)

# --- declared inputs, all imported from oracle.parity rather than named here --------------------

CANONICAL_METADATA = SHIPPED_CANONICAL_METADATA
CANONICAL_FASTA = SHIPPED_CANONICAL_FASTA
SEQUENCE_EVIDENCE = SHIPPED_SEQUENCE_EVIDENCE
SOURCE_FEATURES = SHIPPED_SOURCE_FEATURES
SOURCE_FEATURE_PARTS = SHIPPED_SOURCE_FEATURE_PARTS
SOURCE_FEATURE_QUALIFIERS = SHIPPED_SOURCE_FEATURE_QUALIFIERS

# --- declared columns --------------------------------------------------------------------------

ACCESSION = "accession"
VERSION = "version"
SEQUENCE_SHA256 = "sequence_sha256"
SEQUENCE_LENGTH_NT = "sequence_length_nt"
VIRUS_GROUP = "virus_group"
VIRUS_TYPE = "virus_type"

SEROTYPE_CONFIDENT = "serotype_sequence_confident"
ENTEROVIRUS_TYPE_CONFIDENT = "enterovirus_type_sequence_confident"

POLIOVIRUS = "poliovirus"
NON_POLIO = "non_polio_enterovirus"

# The tier predicate, per group. Verified against the shipped artifacts: applied to the shipped row
# sets these reproduce `POLIO_unified`'s 8,736/1,252 and `NPEV_unified`'s 10,418/3,632 exactly.
# `EV_unified` is the one that does not reproduce exactly, and the reason is known rather than
# mysterious — see `population.tier_of`.
TIER_COLUMN_BY_GROUP = {
    POLIOVIRUS: SEROTYPE_CONFIDENT,
    NON_POLIO: ENTEROVIRUS_TYPE_CONFIDENT,
}
BACKBONE_VALUE = "TRUE"

# `virus_type` is blank for 902 canonical records: 25 poliovirus and 877 non-polio. The two get
# different sentinels, because they are different statements. For polio, "we know it is poliovirus
# and could not resolve the serotype" is upstream's own `PV?` — `POLIO_unified.provenance.json`
# reports `"PV?": 20`. For non-polio there is no serotype to fail to resolve, so labelling those
# rows `PV?` would assert they are poliovirus, which is false for all 877.
BLANK_TYPE_SENTINEL_BY_GROUP = {
    POLIOVIRUS: "PV?",
    NON_POLIO: "unknown",
}


# --- family, for NCR seed stratification -------------------------------------------------------


def family_of(virus_type: str) -> str:
    """Upstream's `ev_unified_common.family_of`, ported verbatim.

    Note the fallback is `"Echo"`, not `"unknown"`: an unprefixed type string is an echovirus by
    upstream's convention, and only an *empty* one is unknown. A rule reconstructed from the shipped
    family counts alone would likely invert that and diverge later, which is why this is a port
    rather than a reimplementation.

    Only the input diverges. Canonical `virus_type` resolves 547 more records than upstream's
    `enterovirus_type`, so over the shipped `NPEV_unified` rows this same rule yields CVA 6,417
    against 6,191, Echo 2,779 against 2,629, CVB 969 against 897, EV-C 783 against 701, EV-B 244
    against 227 and unknown 730 against 1,277, with EV-A, EV-D and the three RV families identical.
    Every one of those deltas is attributable to the type column, which is a stronger and cheaper
    claim than declaring a new rule.
    """
    if not virus_type:
        return "unknown"
    if virus_type.startswith("PV"):
        return "PV"
    if virus_type.startswith("CVA"):
        return "CVA"
    if virus_type.startswith("CVB"):
        return "CVB"
    if virus_type.startswith("EV-"):
        return "EV-" + virus_type[3]
    if virus_type.startswith("RV-"):
        return "RV-" + virus_type[3]
    return "Echo"


# --- per-artifact specification ----------------------------------------------------------------


@dataclass(frozen=True)
class PopulationSpec:
    """Which canonical rows belong to an artifact. Membership only — never a tier or a parameter."""

    virus_groups: tuple[str, ...]
    # None means "every type in the group, including blank". A tuple restricts to those types,
    # which is what excludes the 25 blank-`virus_type` polio records from PV1/PV2/PV3.
    virus_types: tuple[str, ...] | None = None


@dataclass(frozen=True)
class CodonSpec:
    """MAFFT parameters for the codon-aware CDS block.

    `pass1_gap_open` is 4.5 for every artifact. Upstream used 3.0 for polio, which its own source
    documents as a footgun producing a deterministic width blowup (2,514 to 3,911 aa) with no oracle
    benefit; 4.5 was applied once as a CLI override and never propagated. Carrying 3.0 forward would
    be carrying a known bug, so this is a deliberate departure from the parameters that built the
    shipped file, recorded as such in provenance.

    `pass2_local_gap_open` is the larger scientific change and the one to watch. Upstream's own note
    records `--lop` sitting at MAFFT's default -2.00 "through every build", shredding short addon
    fragments; -24.0 was chosen off the interior of a measured plateau but **never reached a shipped
    artifact**. It changes fragment placement for roughly 9,768 addon rows.
    """

    pass1_gap_open: float = 4.5
    pass2_gap_open: float = 6.0
    pass2_local_gap_open: float = -24.0
    # MAFFT's `--ep`, the gap *extension* penalty, applied to both `--add` passes. Upstream never
    # set it, so it sat at MAFFT's default 0.123 through every build — and cheap extension is what
    # lets a single unalignable fragment open a wide insertion block, because opening the gap is
    # paid for once and widening it is nearly free. Measured on POLIO_unified's real pass-1 input
    # (8,730 sequences onto the 6-row seed), CDS width in amino acids:
    #
    #     --op 4.5  --ep 0.123 (default)   2465
    #     --op 4.5  --ep 0.5              2300   <- chosen
    #     --op 6.0  --ep 0.5              2883
    #     --op 8.0  --ep 1.0              2878
    #
    # Note the non-monotonicity: raising `--op` above 4.5 makes the alignment *wider*, because a
    # higher opening cost pushes the aligner away from reusing an existing gapped region and toward
    # opening a fresh column elsewhere. That is the real mechanism behind upstream's `op1 = 3.0`
    # blowing up to 3,911 aa, which its own source recorded only as a bug. `--op` therefore cannot
    # be tuned by intuition in either direction; 4.5 is kept because it measures best.
    #
    # Deliberately not applied to the seed stage: measured there it is a no-op (2,224 aa either
    # way), since six near-identical complete polyproteins have no long gaps to extend, and leaving
    # the seed on defaults keeps the column frame the 2,300 measurement was made against.
    gap_extend: float = 0.5
    seed_min_aa: int = 2000
    seed_per_type: int = 2
    accept_annotated_max_internal_stops: int = 1
    accept_annotated_min_aa: int = 20
    infer_min_aa: int = 20
    infer_max_x_fraction: float = 0.4
    # Typed so no configuration edit can turn it on. `--keeplength` deletes insertion residues,
    # which would break the 1:1 amino-acid-to-codon backtranslate invariant the CDS block rests on.
    # The type is the check; a runtime assertion that argv omits it could never fire.
    keeplength: Literal[False] = False


@dataclass(frozen=True)
class NcrSideSpec:
    """The population window and covariance model for one NCR side (`"5p"` or `"3p"`).

    `pop_max_nt=None` means no ceiling — NPEV's own upstream build never needed one. Where a
    ceiling exists, it excludes records whose NCR fragment is implausibly long for a genuine
    untranslated region — almost always a mis-segmented CDS tail (a GenBank CDS annotation that
    stops short of the true ORF end, so `align.segment` buckets the remainder as "3'NCR") rather
    than real biology. An excluded record is not dropped from the artifact — only its NCR
    fragment is excluded from this side's alignment; it still contributes its CDS block, and gets
    an all-gap NCR block like any other record with no usable fragment on this side.
    """

    pop_min_nt: int
    pop_max_nt: int | None
    cm_path: str


@dataclass(frozen=True)
class NcrSpec:
    five_prime: NcrSideSpec
    three_prime: NcrSideSpec


@dataclass(frozen=True)
class AnchorSpec:
    """The Sabin-anchored CDS block for one serotype: which reference frames the coordinates, and
    the two do-no-harm guards that decide when codon-aware placement is trusted over the plain
    nucleotide anchor. See `align.anchored` for what each guard actually protects against.

    `length_cap` is **not** a membership filter here, and that is a deliberate departure. Upstream
    used 7700 as a *candidacy* pre-filter, before any serotype had been assigned — a step this port
    does not have, because membership is canonical `virus_type` by curator decision. Dropping a
    canonical record for length would break the 1-to-1 row-set rule outright. So it is carried as a
    declared reporting threshold: a record above it is reported, never removed. Worth keeping rather
    than deleting as unreachable — the longest PV record today is 7694 nt, 6 nt of headroom.
    """

    serotype: str
    reference_accession: str
    length_cap: int = 7700
    # Revert to the nucleotide anchor when codon-aware placement worsens CDS nt p-distance by more
    # than this. Fixes short-divergent-fragment amino-acid mis-placement.
    pdist_guard_increase_pp: float = 2.0
    # Override a record's OWN GenBank frame for the ref-inferred one only on overwhelming evidence.
    # Deliberately far above the nt guard: overriding a submitter's annotation needs a real rescue
    # (~70-90% -> <15% amino-acid divergence), not alignment noise.
    aa_guard_increase_pp: float = 30.0
    # Hand-adjudicated per-accession opt-out of the nt guard. Upstream verified this record's
    # guard-rejected codon-aware candidate is genuinely stop-free at comparable coverage, so the
    # guard is a false positive for it; three sibling accessions were checked and rejected.
    pdist_guard_bypass: frozenset[str] = frozenset({"OR538733"})


@dataclass(frozen=True)
class AlignmentSpec:
    name: str
    stack: Literal["unified", "anchored"]
    population: PopulationSpec
    # Expected row count, measured from the shipped 2.4.1 canonical metadata. Recounted from
    # metadata by the tests rather than trusted, so this is a tripwire and not a source of truth.
    expected_rows: int
    # The Stockholm `#=GF DE` line. Deliberately a field of its own rather than shared with any
    # provenance-file description: the shipped unified `#=GF DE` and the shipped provenance
    # `description` already differ from each other, so treating them as one field would be
    # asserting a coincidence that does not hold.
    description: str
    codon: CodonSpec = CodonSpec()
    # Both stacks build their NCR blocks with cmalign; they differ only in which CM. The unified
    # stack uses the genus-wide occupancy-consensus models, the anchored stack the per-serotype
    # `cmbuild --hand` models whose every match column is a real Sabin genome position.
    ncr: NcrSpec | None = None
    # Set only for the anchored stack, whose CDS block is a pairwise reference-frame projection
    # (`align.anchored`) rather than a MAFFT profile alignment (`align.codon`).
    anchor: AnchorSpec | None = None


POLIO_TYPES = ("PV1", "PV2", "PV3")

# EV_unified reuses NPEV's own committed CM on both sides — not a separate "EV" model — exactly as
# upstream's `build_grand_ev_ncr_structural.py` does (its own error message, on a missing CM, names
# `build_ev_ncr_structural.py` — the NPEV script — as the producer to check). Its 3' ceiling (350nt)
# is wider than standalone POLIO_unified's own (150nt): it must still admit NPEV's legitimately
# longer 3'NCR range (observed up to 329nt) while excluding polio's pathological >500nt
# mis-segmented-CDS cluster that the standalone POLIO_unified ceiling was built to exclude.
# The polio population windows, declared once and shared by the genus-wide POLIO_unified models and
# the six per-serotype ones below: same underlying records, same mis-segmented-CDS ceiling.
_POLIO_5P_WINDOW = {"pop_min_nt": 50, "pop_max_nt": 1000}
_POLIO_3P_WINDOW = {"pop_min_nt": 20, "pop_max_nt": 150}

POLIO_NCR = NcrSpec(
    five_prime=NcrSideSpec(**_POLIO_5P_WINDOW, cm_path=f"{SEED_DIR}/polio_ncr_5p.cm"),
    three_prime=NcrSideSpec(**_POLIO_3P_WINDOW, cm_path=f"{SEED_DIR}/polio_ncr_3p.cm"),
)

# The per-serotype Sabin-anchored models. Population windows are POLIO_unified's own, because these
# are the same underlying polio records and the same mis-segmented-CDS ceiling rationale applies.
# What differs is the model: `cmbuild --hand` against that serotype's Sabin reference, so each
# model's match-column count equals its serotype's true UTR length exactly (measured: 742/69,
# 747/68, 742/69 against 5'UTR/3'UTR lengths of the same values). That is what makes the anchored
# stack's stitched width come out at the Sabin genome length rather than merely near it.
PV_NCR = {
    serotype: NcrSpec(
        five_prime=NcrSideSpec(
            **_POLIO_5P_WINDOW, cm_path=f"{SEED_DIR}/{serotype.lower()}_ncr_5p.cm"
        ),
        three_prime=NcrSideSpec(
            **_POLIO_3P_WINDOW, cm_path=f"{SEED_DIR}/{serotype.lower()}_ncr_3p.cm"
        ),
    )
    for serotype in POLIO_TYPES
}

# Each serotype's Sabin whole-genome reference. These are themselves canonical records (verified:
# AY184219/20/21 carry virus_type PV1/PV2/PV3 and lengths 7441/7439/7432), so the reference row is a
# population member rather than an imported outsider.
SABIN_REFERENCE = {"PV1": "AY184219", "PV2": "AY184220", "PV3": "AY184221"}

NPEV_NCR = NcrSpec(
    five_prime=NcrSideSpec(pop_min_nt=50, pop_max_nt=None, cm_path=f"{SEED_DIR}/npev_ncr_5p.cm"),
    three_prime=NcrSideSpec(pop_min_nt=20, pop_max_nt=None, cm_path=f"{SEED_DIR}/npev_ncr_3p.cm"),
)
EV_NCR = NcrSpec(
    five_prime=NcrSideSpec(pop_min_nt=50, pop_max_nt=1000, cm_path=f"{SEED_DIR}/npev_ncr_5p.cm"),
    three_prime=NcrSideSpec(pop_min_nt=20, pop_max_nt=350, cm_path=f"{SEED_DIR}/npev_ncr_3p.cm"),
)

ARTIFACTS: dict[str, AlignmentSpec] = {
    "POLIO_unified": AlignmentSpec(
        name="POLIO_unified",
        stack="unified",
        population=PopulationSpec(virus_groups=(POLIOVIRUS,)),
        expected_rows=10_090,
        description=(
            "All-serotype poliovirus whole-genome multiple sequence alignment "
            "(5'NCR structure-aware, CDS codon-aware, 3'NCR structure-aware)"
        ),
        ncr=POLIO_NCR,
    ),
    "NPEV_unified": AlignmentSpec(
        name="NPEV_unified",
        stack="unified",
        population=PopulationSpec(virus_groups=(NON_POLIO,)),
        expected_rows=14_218,
        description=(
            "Non-polio enterovirus whole-genome multiple sequence alignment "
            "(5'NCR structure-aware, CDS codon-aware, 3'NCR structure-aware)"
        ),
        ncr=NPEV_NCR,
    ),
    "EV_unified": AlignmentSpec(
        name="EV_unified",
        stack="unified",
        population=PopulationSpec(virus_groups=(POLIOVIRUS, NON_POLIO)),
        expected_rows=24_308,
        description=(
            "All-enterovirus (poliovirus and non-polio) whole-genome multiple sequence "
            "alignment (5'NCR structure-aware, CDS codon-aware, 3'NCR structure-aware)"
        ),
        ncr=EV_NCR,
    ),
    "PV1_unified": AlignmentSpec(
        name="PV1_unified",
        stack="anchored",
        population=PopulationSpec(virus_groups=(POLIOVIRUS,), virus_types=("PV1",)),
        expected_rows=4_337,
        description=(
            "Poliovirus serotype 1 whole-genome multiple sequence alignment, Sabin-anchored"
        ),
        ncr=PV_NCR["PV1"],
        anchor=AnchorSpec(serotype="PV1", reference_accession=SABIN_REFERENCE["PV1"]),
    ),
    "PV2_unified": AlignmentSpec(
        name="PV2_unified",
        stack="anchored",
        population=PopulationSpec(virus_groups=(POLIOVIRUS,), virus_types=("PV2",)),
        expected_rows=3_790,
        description=(
            "Poliovirus serotype 2 whole-genome multiple sequence alignment, Sabin-anchored"
        ),
        ncr=PV_NCR["PV2"],
        anchor=AnchorSpec(serotype="PV2", reference_accession=SABIN_REFERENCE["PV2"]),
    ),
    "PV3_unified": AlignmentSpec(
        name="PV3_unified",
        stack="anchored",
        population=PopulationSpec(virus_groups=(POLIOVIRUS,), virus_types=("PV3",)),
        expected_rows=1_597,
        description=(
            "Poliovirus serotype 3 whole-genome multiple sequence alignment, Sabin-anchored"
        ),
        ncr=PV_NCR["PV3"],
        anchor=AnchorSpec(serotype="PV3", reference_accession=SABIN_REFERENCE["PV3"]),
    ),
}

# The Sabin references, and the accession each `PV{n}_unified` is anchored on. Their canonical
# `sequence_length_nt` — 7,441 / 7,439 / 7,432 — equals the shipped
# `n_sabin_reference_columns` exactly, which gives the anchored stack a free integer invariant.
SABIN_REFERENCES = {"PV1": "AY184219", "PV2": "AY184220", "PV3": "AY184221"}

# Reasons a row present in a shipped alignment is absent from the rebuild. Closed vocabulary: a
# drop with no reason is a bug, and a new reason is a source edit that gets reviewed.
DROP_REASONS = (
    "serotype_relabelled",
    "virus_type_lost",
    "group_moved",
    "carve_excluded",
)
