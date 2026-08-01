"""Every `final/` path and column name the site consumes, declared exactly once.

This module is the blast-radius firewall. The generation pipeline is being
rewritten upstream; when a path moves or a column is renamed, this file is the
only one that needs to change. Nothing else under `site/pipeline/` may hardcode a
path into `final/` or a canonical column name.

One upstream change is expected and is marked `# UPCOMING:` below — an added
date-range field. Whether `collection_date` is normalized to ISO is undecided, and
`traits.parse_collection_date` does not depend on the answer: it reads both the ISO
shapes and the ones GenBank records verbatim.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FINAL = REPO_ROOT / "final"
SITE = REPO_ROOT / "site"
DATA_OUT = SITE / "data"

# --- Files read ------------------------------------------------------------

CANONICAL_METADATA = FINAL / "canonical" / "sequence_metadata.tsv.gz"

# `sequence_metadata_vouched.tsv.gz` is deliberately NOT read. It is a
# byte-identical strict subset of the above — 10,086 rows, same 24 columns,
# exactly `curation_status == "vouched"`, zero differing field values. It is a
# filter, not a table, and is exposed in the UI as a curation_status toggle.

RECORD_TAXONOMY = FINAL / "source" / "normalized_tsv" / "record_taxonomy.tsv.gz"
# Carries `retrieval_date` — the day the frozen GenBank snapshot was pulled, which
# is what "source complete as of" on the page means. Not the build date.
RAW_MANIFEST = REPO_ROOT / "raw" / "raw_manifest.json"
# What became of every recorded curator decision in this build. Replaced
# `audit/manual_decisions.tsv.gz` on 2026-08-01: that was 2.4.1's synthesized copy of the
# curation registry, and it is not in the release any more — `final/` is now the pipeline's own
# output and the pipeline does not write it. This table is strictly better for the one thing the
# site asks of it (`has_manual_decision`), because it records whether a decision *reached* the
# record rather than only that one was filed: 3,959 accessions carry an applied decision here
# against 2,237 accessions in the retired file.
DECISION_APPLICATIONS = FINAL / "audit" / "decision_applications.tsv.gz"
DECISION_APPLIED_PREFIX = "applied"
DECISION_STATUS_COLUMN = "application_status"
BUILD_MANIFEST = FINAL / "audit" / "build_manifest.json"
REGION_COORDINATES = FINAL / "alignments" / "reference_region_coordinates.tsv"

ALIGNMENT_DIR = FINAL / "alignments"


def alignment_sto(name: str) -> Path:
    return ALIGNMENT_DIR / f"{name}.sto.gz"


# One provenance record per artifact, since the natively-built alignments were promoted into
# `final/alignments/` on 2026-08-01. 2.4.1 shipped the three per-serotype alignments as a single
# build with one shared `unified_stockholm_provenance.json` that carried no `block_widths` —
# survivable only because the serotype figures use the Sabin frame, which does not need them, and
# only `EV_unified` took the projected frame. Every artifact now carries its own, widths included.
def alignment_provenance(name: str) -> Path:
    return ALIGNMENT_DIR / f"{name}.provenance.json"


# `NPEV_unified` is deliberately unused. It carries no poliovirus reference row,
# so there is no anchor from which to project polyprotein cleavage sites onto its
# columns. Non-polio records are read from `EV_unified`, which does contain
# AY184219/20/21 and puts polio and non-polio in one comparable frame.
UNUSED_ALIGNMENTS = ("NPEV_unified", "POLIO_unified")

# --- Canonical columns -----------------------------------------------------

KEY_ACCESSION = "accession"
KEY_VERSION = "version"

CANONICAL_COLUMNS = (
    "accession",
    "version",
    "sequence_sha256",
    "sequence_length_nt",
    "sequence_scope",
    "ncbi_taxid",
    "organism_name",
    "virus_group",
    "virus_type",
    "poliovirus_classification",
    "curation_status",
    "isolate_name",
    "strain_name",
    "host_name",
    "sample_origin",
    "surveillance_stream",
    "specimen_type",
    "collection_date",
    "collection_date_precision",
    "collection_year_earliest",
    "collection_year_latest",
    "country",
    "admin1",
    "locality",
    "engineered_or_construct",
    "biosample_accession",
)
# The date-range field arrived (2026-07-29, MAD-VDPV schema 2.2.0/2.3.0):
# collection_year_earliest/latest, populated IFF collection_date_precision == 'range'
# (121 records upstream), collection_date holding the midpoint on those rows. Declared
# here only, per this module's own contract -- not added to TRAITS. Whether the bounds
# should be a colorable trait (as opposed to record-inspector-only detail) is a UI
# design call outside the scope of catching the site up to a data refresh.
#
# Whether `collection_date` gets normalized to ISO is undecided — it may stay as GenBank
# recorded it, `Oct-2010` and `2020/2021` included. Nothing here rests on that. The
# parser in traits.py reads both shapes, so the derived decimal year is correct either
# way: if the column is normalized it simply agrees with the raw value, and if it is not
# it keeps doing the work. The record inspector labels it as derived beside the raw
# value rather than replacing it, which is right under either outcome.

GROUP_POLIO = "poliovirus"
GROUP_NPEV = "non_polio_enterovirus"

# --- Genome regions --------------------------------------------------------

# `reference_region_coordinates.tsv` names the thirteen mature peptides plus the
# two untranslated regions, in Sabin coordinates, per serotype.
P1_GENES = ("VP4", "VP2", "VP3", "VP1")
P2_GENES = ("2A", "2B", "2C")
P3_GENES = ("3A", "3B", "3C", "3D")
CDS_GENES = P1_GENES + P2_GENES + P3_GENES

REGION_5NCR = "5NCR"
REGION_3NCR = "3NCR"
REGION_P1 = "P1"
REGION_P2 = "P2"
REGION_P3 = "P3"
REGION_POLYPROTEIN = "polyprotein"

# Region ids paired with the coordinate-table region names they are built from.
# 5UTR/3UTR are the coordinate table's spelling; 5NCR/3NCR is this project's.
CODING_REGIONS = (REGION_POLYPROTEIN, REGION_P1, REGION_P2, REGION_P3)
NONCODING_REGIONS = (REGION_5NCR, REGION_3NCR)

REGION_LABELS = {
    REGION_POLYPROTEIN: "Polyprotein",
    REGION_P1: "P1 (capsid)",
    REGION_P2: "P2",
    REGION_P3: "P3",
    REGION_5NCR: "5′NCR",
    REGION_3NCR: "3′NCR",
}

# Figure set 1 compares translated codons, so it is coding-only. Figure set 2
# works on nucleotide distance and can therefore add the two NCRs.
DIVERGENCE_REGIONS = CODING_REGIONS
DISTANCE_REGIONS = (REGION_5NCR, REGION_P1, REGION_P2, REGION_P3, REGION_3NCR)

# Figure set 3 is the same nucleotide distances set 2 scales, so it covers the same
# regions. Set 4 translates first, so it is coding-only — and excludes the whole
# polyprotein, which at 2,210 codons would say nothing that its three parts do not say
# separately while costing three times the build.
NUCLEOTIDE_TREE_REGIONS = DISTANCE_REGIONS

# Sets 4 and 5 translate first, so they are coding-only — and exclude the whole
# polyprotein, which at 2,210 codons would say nothing that its three parts do not say
# separately while costing three times the build.
PROTEIN_DISTANCE_REGIONS = (REGION_P1, REGION_P2, REGION_P3)
PROTEIN_TREE_REGIONS = PROTEIN_DISTANCE_REGIONS

# --- Thresholds ------------------------------------------------------------

# Coverage below this many nucleotides of comparable material excludes a record
# from a region's panel. The distributions are bimodal — near-complete or absent —
# so this separates "has the region" from "does not", rather than trimming edges.
MIN_REGION_NT = 50

# The 3'NCR alignment block is only 87 columns wide, so 50 nt is a large fraction
# of it and 70% of genus-wide pairs fall below that overlap. Lowered deliberately.
MIN_REGION_NT_BY_REGION = {REGION_3NCR: 30}

# A non-polio reference consensus needs this many contributing rows before it is
# trusted; otherwise the fallback ladder steps up to species, then genus.
MIN_CONSENSUS_ROWS = 5
MIN_CONSENSUS_NT = 30

# Non-synonymous-per-assessable-codon rate above which a record is counted as
# carrying the consensus-coverage artifact that reference.py's `_consensus`
# discloses. Not a quality threshold and nothing is filtered on it — it exists only
# to size the disclosure, so the page states a measured number rather than "a few
# hundred". See summary.consensus_inflation.
CONSENSUS_INFLATION_RATE = 0.5


def min_nt(region: str) -> int:
    return MIN_REGION_NT_BY_REGION.get(region, MIN_REGION_NT)


# --- Selections ------------------------------------------------------------

SABIN_REFERENCE = {"PV1": "AY184219", "PV2": "AY184220", "PV3": "AY184221"}

# Each selection names the alignment that supplies its coordinate frame, and how
# rows are restricted within it. `frame="sabin"` means the alignment's RF match
# columns are exactly that serotype's Sabin genome coordinates, so the region
# coordinate table applies directly. `frame="projected"` means region boundaries
# are projected from Sabin 1 through the alignment's codon MSA.
SELECTIONS = (
    {
        "id": "PV1",
        "label": "Poliovirus 1",
        "alignment": "PV1_unified",
        "frame": "sabin",
        "reference": "AY184219",
        "restrict": None,
        "default_trait": "poliovirus_classification",
        "root": "AY184219",
    },
    {
        "id": "PV2",
        "label": "Poliovirus 2",
        "alignment": "PV2_unified",
        "frame": "sabin",
        "reference": "AY184220",
        "restrict": None,
        "default_trait": "poliovirus_classification",
        "root": "AY184220",
    },
    {
        "id": "PV3",
        "label": "Poliovirus 3",
        "alignment": "PV3_unified",
        "frame": "sabin",
        "reference": "AY184221",
        "restrict": None,
        "default_trait": "poliovirus_classification",
        "root": "AY184221",
    },
    {
        "id": "NPEV",
        "label": "Non-polio enterovirus",
        "alignment": "EV_unified",
        "frame": "projected",
        "reference": "consensus",
        "restrict": GROUP_NPEV,
        "default_trait": "virus_type",
        "root": "midpoint",
    },
    {
        "id": "all",
        "label": "All enterovirus",
        "alignment": "EV_unified",
        "frame": "projected",
        "reference": "consensus",
        "restrict": None,
        "default_trait": "virus_type",
        "root": "AY184219",
    },
)

# The Sabin 1 row in EV_unified is the anchor from which P1/P2/P3 boundaries are
# projected onto the genus-wide codon MSA. Verified: its CDS block is 6,627 nt,
# divisible by three, starting at ATG, and the projected region widths reproduce
# the per-serotype widths (2643 / 1725 / 2259 nt) exactly.
PROJECTION_ANCHOR = "AY184219"
PROJECTION_ANCHOR_SEROTYPE = "PV1"

# --- Traits ----------------------------------------------------------------

# One trait catalog drives every figure set, so a color means the same thing in
# all of them. `source="canonical"` reads the column directly; `source="derived"`
# is computed in traits.py.
TRAITS = (
    {
        "id": "poliovirus_classification",
        "label": "Classification",
        "kind": "discrete",
        "source": "canonical",
        "note": "Empty for every non-polio record.",
    },
    {"id": "virus_type", "label": "Virus type", "kind": "discrete", "source": "canonical"},
    {
        "id": "species",
        "label": "Species",
        "kind": "discrete",
        "source": "derived",
        "note": "Derived from the GenBank taxonomy lineage.",
    },
    {
        "id": "type_concordance",
        "label": "Type concordance",
        "kind": "discrete",
        "source": "derived",
        # Scoped to the selection: the same record is concordant in one serotype's
        # alignment and discordant in another's, so it has no global value.
        "scope": "selection",
        "note": "Curated virus_type against the alignment the record was placed in.",
    },
    {
        "id": "curation_status",
        "label": "Curation status",
        "kind": "discrete",
        "source": "canonical",
    },
    {"id": "sample_origin", "label": "Sample origin", "kind": "discrete", "source": "canonical"},
    {
        "id": "surveillance_stream",
        "label": "Surveillance stream",
        "kind": "discrete",
        "source": "canonical",
    },
    {"id": "specimen_type", "label": "Specimen type", "kind": "discrete", "source": "canonical"},
    {"id": "country", "label": "Country", "kind": "discrete", "source": "canonical"},
    {"id": "host_name", "label": "Host", "kind": "discrete", "source": "canonical"},
    {
        "id": "sequence_scope",
        "label": "Sequence scope",
        "kind": "discrete",
        "source": "canonical",
        "note": "other_fragment for every non-polio record; polio-only in practice.",
    },
    {
        "id": "collection_date_precision",
        "label": "Date precision",
        "kind": "discrete",
        "source": "canonical",
    },
    {
        "id": "engineered_or_construct",
        "label": "Engineered or construct",
        "kind": "discrete",
        "source": "canonical",
    },
    {
        "id": "collection_year",
        "label": "Collection date",
        "kind": "continuous",
        "source": "derived",
        "note": "Decimal year. Records with no parseable date are drawn unfilled.",
    },
    {
        "id": "sequence_length_nt",
        "label": "Sequence length (nt)",
        "kind": "continuous",
        "source": "canonical",
    },
    {
        "id": "region_coverage_nt",
        "label": "Region coverage (nt)",
        "kind": "continuous",
        "source": "computed",
        "scope": "panel",
        "note": "Comparable nucleotides in the region on screen. Varies per panel.",
    },
)

TRAIT_SCOPE_RECORD = "record"

DEFAULT_SELECTION = "PV1"
DEFAULT_REGION = REGION_POLYPROTEIN

# Number of discrete categories given their own hue before the rest collapse into a
# single `Other` bucket. Seven is not a preference: it is the largest number of hues
# that clears all-pairs color-vision separation on a scatter plot. See the
# measurements in site/src/model/palette.ts.
MAX_DISCRETE_CATEGORIES = 7
OTHER_CATEGORY = "Other"
MISSING_CATEGORY = "not recorded"

# --- Derived-trait vocabularies -------------------------------------------

CONCORDANT = "concordant"
DISCORDANT = "discordant"
UNALIGNED = "unaligned"

# Traits whose categories have a declared meaning rather than an incidental
# frequency. Ranking these by count would exile `Sabin` — 46 records, and the
# reference every polio panel is measured against — into `Other`, which is exactly
# backwards. Values absent from the list still fall to `Other`.
CATEGORY_ORDER = {
    "poliovirus_classification": [
        "Sabin",
        "Sabin-like",
        "VDPV",
        "cVDPV",
        "iVDPV",
        "wild",
        "unresolved",
    ],
    "type_concordance": [CONCORDANT, DISCORDANT, UNALIGNED],
    "curation_status": ["vouched", "provisional"],
}

# SWITCHOVER: species is derived here because `final/canonical/` ships no species
# column. The taxonomy table uses post-2023 ICTV binomials rather than the
# EV-A..EV-D / RV-A..RV-C labels this field is universally reported in, so the
# mapping is explicit. When canonical gains a native species column, delete this
# map and the `derive_species` call in traits.py and read the column instead.
SPECIES_BINOMIAL = {
    "Enterovirus alphacoxsackie": "EV-A",
    "Enterovirus betacoxsackie": "EV-B",
    "Enterovirus coxsackiepol": "EV-C",
    "Enterovirus deconjuncti": "EV-D",
    "Enterovirus eibovi": "EV-E",
    "Enterovirus fitauri": "EV-F",
    "Enterovirus geswini": "EV-G",
    "Enterovirus hesimi": "EV-H",
    "Enterovirus jesimi": "EV-J",
    "Enterovirus alpharhino": "RV-A",
    "Enterovirus betarhino": "RV-B",
    "Enterovirus cerhino": "RV-C",
    # Legacy pre-binomial labels still present on a handful of records.
    "Enterovirus A": "EV-A",
    "Enterovirus B": "EV-B",
    "Enterovirus C": "EV-C",
    "Enterovirus D": "EV-D",
    "Rhinovirus A": "RV-A",
    "Rhinovirus B": "RV-B",
    "Rhinovirus C": "RV-C",
}
GENUS_TAXA = ("Enterovirus", "Rhinovirus")
SPECIES_UNRESOLVED = "unresolved"

# Fallback when the taxonomy lineage stops AT genus with no species-rank child at all
# (269 records, 2026-07-29) -- `derive_species` then has nothing to look up, but for some
# of those the `organism_name` field already states the species and the lineage gap is
# simply an NCBI taxonomy-record completeness gap, not real ambiguity. Two disjoint cases:
#   - 82 records: organism_name IS ALREADY an exact SPECIES_BINOMIAL key ("Enterovirus
#     coxsackiepol" etc). No new data needed, just falling back to the same table.
#   - 11 records: organism_name is "Human poliovirus sp." -- not an ICTV binomial (hence
#     not a SPECIES_BINOMIAL key), but poliovirus has no non-EV-C serotype, so this is
#     unambiguous and does not need sequence evidence to resolve.
# The remaining ~176 genus-terminal records are genuinely ambiguous (vague pre-binomial
# forms like "Human enterovirus", "Enterovirus 6/19/24", or non-human "Simian enterovirus
# SV46") and correctly stay `unresolved` -- this map must never grow to cover them.
SPECIES_ORGANISM_FALLBACK = {
    "Human poliovirus sp.": "EV-C",
}

# Alignment character semantics live in frame.py, which owns the normalized
# encoding: rows mix case, the NCR blocks use U where the CDS block uses T, and
# everything outside ACGT counts as not-covered rather than as a mismatch.

# --- Gated inputs ----------------------------------------------------------


def gated_inputs() -> tuple[Path, ...]:
    """Files whose bytes the generated site artifacts depend on.

    Their hashes are recorded in `site/data/manifest.json` and published with the
    figures, so a page can be traced to the exact inputs behind it. They no longer
    gate anything: the artifacts are rebuilt per deploy rather than committed, so a
    data change reaches the page by rebuilding rather than by passing a check.
    """
    paths = [
        CANONICAL_METADATA,
        RECORD_TAXONOMY,
        DECISION_APPLICATIONS,
        REGION_COORDINATES,
        BUILD_MANIFEST,
        RAW_MANIFEST,
    ]
    used = {s["alignment"] for s in SELECTIONS}
    paths.extend(alignment_sto(name) for name in sorted(used))
    paths.extend(sorted({alignment_provenance(name) for name in used}))
    return tuple(paths)


def repo_relative(path: Path) -> str:
    return path.relative_to(REPO_ROOT).as_posix()
