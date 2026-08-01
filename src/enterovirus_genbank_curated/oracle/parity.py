"""Check a rebuild of the source layer, and the metadata build's declared declines.

## What retired here, and when

Until 2026-08-01 this module also compared the metadata transport to `final/` cell by cell, and
its provenance row by row. `final/` now *is* this pipeline's output — see `build.reject_immutable_
output` and `docs/reproducibility.md` — so those comparisons would read the build's own bytes and
pass by construction. A gate that cannot fail is worse than an absent one, so they were deleted
rather than left green.

What survives is the part that still has an oracle:

* **The source layer**, compared by **file hash** against `oracle.release.SOURCE_LAYER_HASHES` —
  hashes pinned in code, carried forward from the 2.4.1 manifest before the metadata build began
  rewriting that file. Every one of its artifacts is fully regenerated from `raw/`, so a byte
  comparison is the right shape.
* **The declared declines**, checked against a fresh metadata build. These are not release
  comparisons: `UNRESOLVED_*` states how many cells each rule refuses to decide, and a rule quietly
  starting to guess (or a decision quietly resolving a population) moves a number here whether or
  not any release exists to compare against.

## Why the build runs in a child process

`--guard-inputs` on a `parity-*` verb used to install the audit hook in the *same* process that then
read `final/` to compare. That made the guard structurally unable to catch the thing it exists to
catch here: a build that read the comparison target would look identical to the comparison itself.
The build runs as a guarded child and the check happens in the unguarded parent, so `sandbox`'s
refusal to read a `final/` file the build did not itself write applies to the build and only to the
build.

`sandbox.ESCAPE_EVENTS` refuses `subprocess`, so the parent cannot be guarded — it is the process
doing the spawning and the release reading. That is the intended arrangement, not a gap.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from enterovirus_genbank_curated.build import build_metadata_layer, build_source_layer
from enterovirus_genbank_curated.contracts import ContractError, sha256_file
from enterovirus_genbank_curated.export.metadata import read_projection_provenance
from enterovirus_genbank_curated.genbank.parse import TABLE_COLUMNS
from enterovirus_genbank_curated.oracle.release import SOURCE_LAYER_HASHES

SHIPPED_SOURCE_DIR = "final/source"
SHIPPED_CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"
VERSION_COLUMN = "version"
GUARD_PASS_MARKER = "undeclared-input guard: PASS"

# `final/` paths the alignment layer (`align/`) derives from, declared here rather than in
# `align/contract.py` so that module has exactly one path to `final/canonical/sequence_metadata`
# rather than two. `align/` reads the release for the same reason this module does, so it is
# oracle-adjacent rather than a build module, and `test_module_boundaries.py` does not constrain it.
# It still must not *redeclare* a path oracle already owns; `SHIPPED_CANONICAL_METADATA` above is
# that path for the canonical metadata table.
#
# Note that `align/` is pinned to 2.4.1 rather than waiting on stages that do not exist —
# `derive/`+`curate/` now build a full canonical table. `SHIPPED_SEQUENCE_EVIDENCE` in particular
# has no successor: `derive/evidence.py` deliberately writes a different, narrower schema, so the
# tier predicate in `align/population.py` has no native producer. See `align/__init__.py` and
# `docs/reproducibility.md`'s "The alignment layer's anchor".
SHIPPED_CANONICAL_FASTA = "final/canonical/sequences.fasta.gz"
SHIPPED_SEQUENCE_EVIDENCE = "final/audit/sequence_evidence.tsv.gz"
# The curation ledger's per-record disposition. Read by `align.shape` so a shipped alignment row
# absent from a rebuild can be attributed to a deliberate carve exclusion rather than merely
# observed to be missing from canonical.
SHIPPED_RECORD_DISPOSITION = "final/audit/record_disposition.tsv.gz"
SHIPPED_SOURCE_FEATURES = "final/source/normalized_tsv/features.tsv.gz"
SHIPPED_SOURCE_FEATURE_PARTS = "final/source/normalized_tsv/feature_location_parts.tsv.gz"
SHIPPED_SOURCE_FEATURE_QUALIFIERS = "final/source/normalized_tsv/feature_qualifiers.tsv.gz"


def run_guarded_build(repository_root: Path, verb: str, output_dir: Path) -> None:
    """Run one build verb in a guarded child, and require the guard to have passed.

    Checking the marker rather than only the exit status matters: a build that never installed the
    guard also exits 0, and this function exists to establish that the guard was in force while the
    artifacts under comparison were produced.
    """
    result = subprocess.run(
        [
            sys.executable, "-m", "enterovirus_genbank_curated.cli", verb,
            "--repository-root", str(repository_root),
            "--output", str(output_dir),
            "--guard-inputs",
        ],
        capture_output=True, text=True, cwd=repository_root, timeout=1800, check=False,
    )
    combined = result.stdout + result.stderr
    if result.returncode != 0:
        raise ContractError(f"guarded `evgc {verb}` failed:\n{combined}")
    if GUARD_PASS_MARKER not in result.stdout:
        raise ContractError(
            f"guarded `evgc {verb}` exited 0 without reporting {GUARD_PASS_MARKER!r}, so the "
            f"artifacts it produced are not covered by the guard:\n{combined}"
        )


def compare_source_to_release(repository_root: Path, built_dir: Path) -> dict[str, str]:
    """Compare every regenerated artifact against the hash pinned in `SOURCE_LAYER_HASHES`.

    Comparing against the on-disk copy in `final/source/` would be self-certifying: a build that
    had overwritten the release would then be compared against itself and pass. The authority used
    to be `final/audit/release_file_manifest.tsv`; since 2026-08-01 that file is regenerated by
    every metadata build, so it can no longer be an oracle for anything, and the source layer's
    hashes moved into `oracle/release.py` as code. The on-disk copy is checked too, so a tampered
    release is reported separately from a bad build.

    Covers the twelve TSVs and the twelve Parquet files. Only `genbank_source.duckdb` is excluded,
    because DuckDB file bytes are genuinely not reproducible.
    """
    declared = dict(SOURCE_LAYER_HASHES)

    results: dict[str, str] = {}
    for relative, expected in sorted(declared.items()):
        built = built_dir / Path(relative).relative_to("source")
        shipped = repository_root / SHIPPED_SOURCE_DIR / Path(relative).relative_to("source")
        if not built.is_file():
            results[relative] = f"not produced by the build: {built}"
            continue
        built_hash = sha256_file(built)
        if built_hash != expected:
            results[relative] = f"rebuilt sha256 {built_hash} != pinned {expected}"
            continue
        if not shipped.is_file():
            results[relative] = f"shipped artifact missing: {shipped}"
            continue
        shipped_hash = sha256_file(shipped)
        if shipped_hash != expected:
            results[relative] = (
                f"shipped artifact does not match its pinned hash ({shipped_hash} != {expected}) "
                f"— the release on disk has been altered"
            )
            continue
        results[relative] = "match"
    return results


def verify_source_parity(repository_root: Path, *, guarded: bool = False) -> dict[str, str]:
    """Rebuild the source layer and check it against the hashes pinned in code."""
    expected_tables = {f"source/normalized_tsv/{name}.tsv.gz" for name in TABLE_COLUMNS}
    missing = sorted(expected_tables - set(SOURCE_LAYER_HASHES))
    if missing:
        raise ContractError(
            f"SOURCE_LAYER_HASHES does not pin byte hashes for {missing}; parity would silently "
            f"skip them"
        )

    with tempfile.TemporaryDirectory(prefix="evgc-parity-") as scratch:
        if guarded:
            run_guarded_build(repository_root, "build-source", Path(scratch))
        else:
            build_source_layer(repository_root, Path(scratch), relational=True)
        results = compare_source_to_release(repository_root, Path(scratch))

    mismatches = {k: v for k, v in results.items() if v != "match"}
    if mismatches:
        detail = "; ".join(f"{k}: {v}" for k, v in sorted(mismatches.items()))
        raise ContractError(f"source layer does not reproduce the shipped release — {detail}")
    return results

# Declared residuals live here rather than beside the rules, so the build cannot reach them at all:
# `tests/test_module_boundaries.py` forbids `derive/` from importing `oracle`. The two sets in
# `derive/metadata.py` predate this file and should move here too.
#
# `virus_group` declines on every record whose organism name cannot determine polio membership — the
# polio-containing species at species level, the bare genus, or a non-identification, and that R-
# MEMBERSHIP-AA-1's own capsid-AA two-sided band does not settle either. Upstream resolved these by
# capsid amino-acid distance (R-MEMBERSHIP-AA-1).
#
# The count is the *input* population, not the population where a default would have landed wrong.
# That second number is 414, and an earlier draft of this work mistook it for the size of the
# problem — which is how a rule ends up scoring 98.3% by guessing.
#
# 1,855 = 1,765 records carrying an uninformative organism name in the shipped canonical table
#         − 2 that are `SEQUENCE_RESCUED_INCLUSIONS` and so are not in the carve at all
#         − 15 carved ones the ledger's `is_poliovirus` decisions resolve
#              (17 such decisions exist; 2 are on records literally named `Poliovirus 2`/`3`, which
#               the name predicate already decides, so only 15 land on uninformative names)
#         + 99 a review found were being guessed: 95 named `Human enterovirus`, the unqualified
#           pre-2016 species name, and 4 named for a strain rather than a type
#         + 8 the membership rescue admits and the release excludes (`UNDECLARED_EXCLUSIONS` less
#           AF326751.2, which the genus predicate already reached)
#         − 259 whose partition a curated *classification* now entails: the value comes from a
#           poliovirus-only vocabulary, so asserting it asserts membership. See derive/partition.py.
#           All 259 ship as poliovirus/vouched in 2.4.1, so this moves three columns toward parity.
#
# The whole +23 of the membership rescue lands here, and that is the expected shape rather than a
# surprise: a record is rescued *because* its organism name is `unidentified`, `synthetic construct`
# or `Homo sapiens`, which is exactly the name the partition rule cannot decide from. The sequence
# settles membership in the carve; it does not write the column — R-PARTITION-2 reads the name.
#
# 1,596 fell to 1,385 on 2026-08-01: `derive.evidence.measure_poliovirus_membership_band` resolves
# 211 of them directly, using the parameters R-MEMBERSHIP-AA-1 already declares for the carve-rescue
# half above — below 8.0% capsid-AA distance from a poliovirus reference rescues to `poliovirus`
# (140), at or above 15.0% confirms `non_polio_enterovirus` (71), and the 8-15% middle (or under 50
# compared codons) stays declined exactly as before. Validated per record against the shipped
# `virus_group`: all 71 `non_polio_enterovirus` calls agree; of the 140 `poliovirus` calls, 138 agree
# and the other 2 are not in the 24,299 shared rows at all (not a disagreement — there is nothing on
# the release side to disagree with). `poliovirus_classification` benefits too: a `poliovirus`-banded
# record with no name serotype now measures VP1/capsid divergence against the band's own identified
# serotype (`BASIS_VP1_BY_MEMBERSHIP_BAND`/`BASIS_CAPSID_BY_MEMBERSHIP_BAND` in `derive/evidence.py`),
# not a name that was never going to state it.
#
# 1,385 fell to **0** on 2026-08-01 (commit `c245dd3`). The upstream release already assigns 1,379
# of them, projected into the ledger as `is_poliovirus` decisions under
# `upstream_partition_projection_2026-08-01`; the remaining six — `A08076` and `HW505760`/`61`/`72`/
# `73`/`74` — are absent upstream and 70-100 nt, far below the 50 compared codons the capsid-AA band
# needs, and the curator calls them poliovirus fragments directly. No record now ships a blank
# partition.
#
# Kept as a named zero rather than deleted, like `UNRESOLVED_ENGINEERED_ROWS` below: the next
# organism name the rule cannot decide from should fail this gate rather than appear as a new key
# nobody pinned. It is also the load-bearing one — `align/population.py` requires a partition on
# every row, so a decline here is not a blank cell but a broken alignment layer.
UNRESOLVED_PARTITION_ROWS = 0
# `specimen_type` rows R-SPECIMEN-2 declines, over the built carve: those where no keyword matches
# `/isolation_source` and 4 where two categories match, naming two specimens rather than one. All 23
# rescued records decline — patent deposits carry no `/isolation_source` — so this moved with them.
UNRESOLVED_SPECIMEN_ROWS = 12700
# `sample_origin` rows R-ORIGIN-2 declines, over the built carve: poliovirus records that
# deposited neither a `/host` nor a recognisable human specimen, plus those whose partition is
# itself undecided and so cannot be scoped either way. 19 of the 23 rescued records decline; the
# other four carry an active `origin_class` decision (E01570, E01572 vaccine; HV932178 human;
# MA400487 non-human). Down 30 from 3,712 when the curated-classification entailment landed: those
# 30 records are now scoped as poliovirus and read their `/host`, 26 of them into the already-
# declared `human` vs shipped `unknown` disagreement and 4 into agreement.
#
# Down a further 21, 2026-08-01, when the capsid-AA membership band resolved `virus_group` directly
# for 140 more records: 21 of them deposit a `/host` and so read it here for the first time; the
# other 119 have none and stay declined.
#
# Down a further 759 the same day, when the upstream partition projection closed `virus_group`
# entirely: those 759 are now scoped and read their `/host`. The rest of the 1,385 newly-partitioned
# records deposit no `/host` and no recognisable human specimen, so they stay declined here — a
# resolved partition makes the question askable, not answered.
UNRESOLVED_ORIGIN_ROWS = 2902
# `surveillance_stream` rows R-SURVEILLANCE-2 declines: 7,342 whose text names no surveillance
# context at all — including the 2,823 poliovirus records the release spreads across all seven of
# its values — plus those whose partition is undecided and so cannot be scoped either way. 20 of the
# 23 rescued records decline; E01570, E01572 and HV932178 carry an active `sampling_frame` decision.
#
# Down a further 56, 2026-08-01, when the capsid-AA membership band resolved `virus_group` directly
# for 211 more records: 56 of them name a surveillance context in their own text and read it here for
# the first time; the rest do not and stay declined.
#
# Down a further 1,023 the same day, with the upstream partition projection. Same shape as
# `sample_origin` above: a scoped record can be asked the question, and 1,023 of the newly-scoped
# ones name a surveillance context in their own text. The others name none.
UNRESOLVED_STREAM_ROWS = 7571
# `engineered_or_construct` now declines on nothing. It declined on `LY501105` and `LZ216100`, the
# CAVA cold-adaptation pair Appendix B of the re-adjudication recorded as open in either direction,
# and the curator closed both FALSE on 2026-07-31 on the precedent already set inside patent
# WO2006042156 — a parental deposit is FALSE, only the constructed product is TRUE. The rule still
# declines rather than emitting a structural FALSE where no decision exists; there is simply no
# such record left. Kept as a named zero so the next one to appear fails this gate rather than
# passing.
UNRESOLVED_ENGINEERED_ROWS = 0
# `virus_type` rows R-TYPE-2 declines: 2,179 whose organism name states no type — species-level
# names like `Enterovirus C`, the pre-2016 bare numbering (`Enterovirus 19`), simian species outside
# A-to-D scheme (`Enterovirus J115`), and the chimera label `Enterovirus coxsackiepol` the release
# types PV2 — plus 37 where an active decision records the type as `unknown`, which is a curator
# stating that it is undetermined. All 23 rescued records land in the first group, for the same
# reason they land in `UNRESOLVED_PARTITION_ROWS`.
UNRESOLVED_TYPE_ROWS = 2216
# `poliovirus_classification` rows R-CLASS-2 declines: 1,596 whose virus group is itself undecided,
# 1,409 poliovirus records with too little usable sequence by either basis to measure divergence
# over, 33 with no serotype in the organism name to pick a Sabin reference with, and 3 whose active
# decision asserts a value outside the declared controlled vocabulary.
#
# Down 259 from 3,448 when a curated classification began entailing membership — every one of those
# 259 is a curated call the previous order threw away: the partition declined on an uninformative
# organism name, this rule declined for "following" it, and the `classification` decision stating
# cVDPV or wild was never read. A rule declining because a *weaker* signal was silent is the failure
# mode; see derive/partition.py.
#
# Down a further 148 from 3,189 when the capsid (P1) nucleotide fallback landed: of the 1,911
# carved, name-serotyped records VP1 alone cannot reach, 159 clear the fallback's own guards, and
# 11 of those already had an active ledger decision that would have resolved them regardless, so
# only 148 newly resolve here. All 148 agree with the shipped classification wherever 2.4.1 has one
# to compare against — the same measured floor and homogeneity guard `derive/evidence.py` documents,
# applied to the real corpus rather than to the three records that motivated it.
#
# Down a further 3 on 2026-07-31 when the vocabulary repairs resolved `AJ416942`, `DQ205099` and
# `FJ517648`, whose active decisions the rule was declining rather than shipping (an out-of-
# vocabulary asserted value) until each was repaired to a value the controlled vocabulary contains.
# The 115 cVDPV/strain-identity decisions the same day do not move this count: every one of those
# 115 already had a resolved value before the decision, just the wrong one, so none was declined.
#
# Down a further 28 the same day: 24 reference_or_lab_text records (12 `Sabin`, 10 `engineered/lab`,
# 1 `recombinant/lab`, 1 `reference/lab` — strain-identity/patent deposits too short to reach a
# divergence measurement) and 4 more `group_A_text_owned` `cVDPV` records, none of which had a prior
# decision, so all 28 leave the declined population for the first time.
#
# Down a further 60 the same day, when `MIN_VP1_NT`/`MIN_CAPSID_NT` dropped to 50 nt (MAD-VDPV's own
# `MIN_SEROTYPE_COMPARED_NT`), guarded by extending the chunked-homogeneity check to VP1 below its
# old 300 nt floor. Every one of the 60 agrees with the shipped classification.
#
# Down a further 708 the same day, when the reference-title text fallback landed
# (`needs_other_data_text_fallback`): every one of the 708 had no divergence measurement by either
# basis and so was declined before; 705 landed on the value 2.4.1 shipped and 3 did not — a decline
# turned into a value either way, which is what leaves the declined population. (The per-column
# disagreement tables those figures were declared in retired with the release comparison; the
# measurements are kept here as the history of how this number got where it is.)
#
# Down a further 191 the same day, when isolate-linked inference landed: 192 candidates, 191 applied
# (one, a short unverified key with no batch corroboration, stays declined). 190 of the 191 landed on
# the value 2.4.1 shipped; the one that did not was `X70506`.
#
# Down a further 211, 2026-08-01, when the capsid-AA membership band resolved `virus_group` directly:
# 71 records banded `non_polio_enterovirus` resolve to a determined blank (`not_applicable_outside_
# poliovirus`, the same value the release ships for every non-poliovirus row) rather than declining
# for "following" an undecided partition, and the other 140 banded `poliovirus` now measure VP1/
# capsid divergence against the band's own identified serotype and resolve outright — 130 of the 140
# landed on the value 2.4.1 shipped, 8 genuinely disagreed, and 2 were not in the shared carve at
# all.
#
# Down a further 1,364 on 2026-08-01, when the upstream partition projection closed `virus_group`:
# this rule declined on 1,385 records for "following" an undecided partition and now follows a
# decided one instead — 1,364 of them resolve outright (most to the determined blank
# `not_applicable_outside_poliovirus`, since the projection lands far more records in
# `non_polio_enterovirus` than in `poliovirus`), and 21 are newly-scoped poliovirus records that
# still have too little usable sequence to measure divergence over.
UNRESOLVED_CLASSIFICATION_ROWS = 476
PARTITION_FIELDS = ("virus_group", "curation_status")


# Canonical field -> the declared decline count above. Every field a rule can decline appears here,
# including `engineered_or_construct`'s zero: a named zero fails when the first new decline appears,
# where an absent key would simply not be looked at.
DECLARED_DECLINES = {
    "virus_group": UNRESOLVED_PARTITION_ROWS,
    "curation_status": UNRESOLVED_PARTITION_ROWS,
    "specimen_type": UNRESOLVED_SPECIMEN_ROWS,
    "sample_origin": UNRESOLVED_ORIGIN_ROWS,
    "surveillance_stream": UNRESOLVED_STREAM_ROWS,
    "engineered_or_construct": UNRESOLVED_ENGINEERED_ROWS,
    "virus_type": UNRESOLVED_TYPE_ROWS,
    "poliovirus_classification": UNRESOLVED_CLASSIFICATION_ROWS,
}


def count_declines(provenance: list[dict[str, str]]) -> dict[str, int]:
    """Declined cells per canonical field, over one build's projection provenance."""
    counts: dict[str, int] = {}
    for row in provenance:
        if row["unresolved_reason"]:
            field = row["canonical_field"]
            counts[field] = counts.get(field, 0) + 1
    return counts


def verify_metadata_declines(
    repository_root: Path, *, guarded: bool = False
) -> dict[str, int]:
    """Rebuild the metadata layer and require its declines to be exactly the declared ones.

    This is what replaced the cell-by-cell release comparison, and it is a different kind of claim:
    not "the build agrees with 2.4.1" but "the build declines where this repository says it
    declines". It needs no oracle, so it survives `final/` becoming the build's own destination,
    and it still fails on the change that matters most — a rule that quietly starts guessing where
    it used to refuse.
    """
    with tempfile.TemporaryDirectory(prefix="evgc-declines-") as scratch:
        if guarded:
            run_guarded_build(repository_root, "build-metadata", Path(scratch))
            provenance = read_projection_provenance(Path(scratch))
        else:
            provenance = build_metadata_layer(repository_root, Path(scratch)).provenance

    counts = count_declines(list(provenance))
    observed = {field: counts.get(field, 0) for field in DECLARED_DECLINES}
    undeclared = {f: n for f, n in counts.items() if f not in DECLARED_DECLINES and n}
    if undeclared:
        raise ContractError(
            f"fields declined that no count is declared for: {sorted(undeclared)}; a decline "
            f"nobody declared is a rule change nobody reviewed"
        )
    if observed != DECLARED_DECLINES:
        differing = {
            f: (observed[f], DECLARED_DECLINES[f])
            for f in DECLARED_DECLINES
            if observed[f] != DECLARED_DECLINES[f]
        }
        detail = "; ".join(
            f"{f}: built {b}, declared {d}" for f, (b, d) in sorted(differing.items())
        )
        raise ContractError(f"declined-cell counts moved — {detail}")
    return observed
