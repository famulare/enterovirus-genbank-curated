"""Compare a rebuild against the shipped release.

Two comparison shapes, and the difference is not cosmetic. The source layer is compared by **file
hash**, because every one of its artifacts is fully regenerated. The metadata transport is compared
**cell by cell**, because it fills thirteen of twenty-six canonical columns and its bytes are
legitimately not the release's bytes.

## Why the build runs in a child process

`--guard-inputs` on a `parity-*` verb used to install the audit hook in the *same* process that then
read `final/` to compare. That made the guard structurally unable to catch the thing it exists to
catch here: a build that read the comparison target would look identical to the comparison itself.
The build now runs as a guarded child and the comparison happens in the unguarded parent, so
`sandbox`'s refusal to read `final/` applies to the build and only to the build.

`sandbox.ESCAPE_EVENTS` refuses `subprocess`, so the parent cannot be guarded — it is the process
doing the spawning and the release reading. That is the intended arrangement, not a gap.
"""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.build import build_metadata_layer, build_source_layer
from enterovirus_genbank_curated.contracts import (
    CANONICAL_COLUMNS,
    ContractError,
    sha256_file,
)
from enterovirus_genbank_curated.derive.metadata import (
    SEQUENCE_RESCUED_INCLUSIONS,
    UNDECLARED_EXCLUSIONS,
)
from enterovirus_genbank_curated.export.audit import PROVENANCE_COLUMNS
from enterovirus_genbank_curated.export.metadata import (
    TRANSPORT_COLUMN_ORDER,
    read_metadata_transport,
    read_projection_provenance,
)
from enterovirus_genbank_curated.genbank.parse import TABLE_COLUMNS
from enterovirus_genbank_curated.oracle.release import (
    RELEASE_FILE_MANIFEST_PATH,
    load_release_file_manifest,
    read_tsv_gz,
)

SHIPPED_SOURCE_DIR = "final/source"
SHIPPED_CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"
SHIPPED_PROVENANCE = "final/audit/canonical_projection_provenance.tsv.gz"
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


def _release_declared_hashes(repository_root: Path) -> dict[str, str]:
    """`file_bytes` hashes the release itself declares, for every `source/` artifact."""
    manifest = load_release_file_manifest(repository_root / RELEASE_FILE_MANIFEST_PATH)
    return {
        path: sha256
        for path, (scope, sha256) in manifest.items()
        if path.startswith("source/") and scope == "file_bytes"
    }


def compare_source_to_release(repository_root: Path, built_dir: Path) -> dict[str, str]:
    """Compare every regenerated artifact against the hash the RELEASE MANIFEST declares.

    Comparing against the on-disk copy in `final/source/` would be self-certifying: a build that
    had overwritten the release would then be compared against itself and pass. The authority is
    `final/audit/release_file_manifest.tsv`, which is covered by `evgc validate-contracts`. The
    on-disk copy is checked too, so a tampered release is reported separately from a bad build.

    Covers the twelve TSVs and the twelve Parquet files — every `source/` artifact the manifest
    declares at `file_bytes` scope. Only `genbank_source.duckdb` is excluded, because DuckDB file
    bytes are genuinely not reproducible; the manifest records a `logical_content` hash for it.
    """
    declared = _release_declared_hashes(repository_root)
    if not declared:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} declares no byte-hashed source/ artifacts; there is "
            f"nothing to compare against"
        )

    results: dict[str, str] = {}
    for relative, expected in sorted(declared.items()):
        built = built_dir / Path(relative).relative_to("source")
        shipped = repository_root / SHIPPED_SOURCE_DIR / Path(relative).relative_to("source")
        if not built.is_file():
            results[relative] = f"not produced by the build: {built}"
            continue
        built_hash = sha256_file(built)
        if built_hash != expected:
            results[relative] = f"rebuilt sha256 {built_hash} != manifest {expected}"
            continue
        if not shipped.is_file():
            results[relative] = f"shipped artifact missing: {shipped}"
            continue
        shipped_hash = sha256_file(shipped)
        if shipped_hash != expected:
            results[relative] = (
                f"shipped artifact does not match its own manifest ({shipped_hash} != {expected}) "
                f"— the release on disk has been altered"
            )
            continue
        results[relative] = "match"
    return results


def verify_source_parity(repository_root: Path, *, guarded: bool = False) -> dict[str, str]:
    """Rebuild the source layer and check it against the release's own manifest."""
    declared = _release_declared_hashes(repository_root)
    expected_tables = {f"source/normalized_tsv/{name}.tsv.gz" for name in TABLE_COLUMNS}
    missing = sorted(expected_tables - set(declared))
    if missing:
        raise ContractError(
            f"{RELEASE_FILE_MANIFEST_PATH} does not declare byte hashes for {missing}; parity "
            f"would silently skip them"
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


@dataclass(frozen=True)
class MetadataParityResult:
    compared_rows: int
    compared_columns: tuple[str, ...]
    shipped_rows: int
    built_rows: int
    absent_from_build: tuple[str, ...]
    absent_from_release: tuple[str, ...]


def compare_metadata_to_release(
    repository_root: Path, rows: list[dict[str, str]]
) -> MetadataParityResult:
    """Compare the transport to the shipped canonical table cell by cell.

    Not a file hash, and it cannot be one: the transport fills thirteen of twenty-six columns, so
    its bytes are legitimately not the release's bytes. What is being claimed is narrower and
    checkable — every cell this stage produces equals the shipped cell, for every record both
    agree belongs in the carve.

    The row-set difference is compared against the two declared residual sets rather than merely
    reported. A record drifting in or out of the carve is a scientific change, and
    `docs/pipeline.md`'s review stop conditions say that fails rather than gets absorbed.
    """
    header, shipped_rows = read_tsv_gz(repository_root / SHIPPED_CANONICAL_METADATA)
    if tuple(header) != CANONICAL_COLUMNS:
        raise ContractError(
            f"{SHIPPED_CANONICAL_METADATA} columns are not the declared canonical schema; "
            f"release header is {header}"
        )
    index = {column: position for position, column in enumerate(header)}
    shipped = {row[index[VERSION_COLUMN]]: row for row in shipped_rows}
    if len(shipped) != len(shipped_rows):
        raise ContractError(f"{SHIPPED_CANONICAL_METADATA} has duplicate {VERSION_COLUMN} values")
    built = {row[VERSION_COLUMN]: row for row in rows}
    if len(built) != len(rows):
        raise ContractError(f"the transport produced duplicate {VERSION_COLUMN} values")

    absent_from_build = frozenset(shipped) - frozenset(built)
    absent_from_release = frozenset(built) - frozenset(shipped)
    if absent_from_build != SEQUENCE_RESCUED_INCLUSIONS:
        raise ContractError(
            "the canonical row-set gap is not the declared one: expected "
            f"{sorted(SEQUENCE_RESCUED_INCLUSIONS)}, got {sorted(absent_from_build)}"
        )
    if absent_from_release != UNDECLARED_EXCLUSIONS:
        raise ContractError(
            "the transport includes records the release excludes, beyond the declared set: "
            f"expected {sorted(UNDECLARED_EXCLUSIONS)}, got {sorted(absent_from_release)}"
        )

    # Row order, not only row membership. Both tables are the version-sorted corpus restricted to a
    # carve, so the shared records must appear in the same sequence — a table that agrees cell for
    # cell but shuffles rows would still not be the release table.
    shared_built = [row[VERSION_COLUMN] for row in rows if row[VERSION_COLUMN] in shipped]
    shared_shipped = [v for v in shipped if v in built]
    if shared_built != shared_shipped:
        raise ContractError(
            "the transport emits the shared records in a different order than the shipped release"
        )

    differences: list[str] = []
    for version in sorted(frozenset(built) & frozenset(shipped)):
        release_row = shipped[version]
        for column in TRANSPORT_COLUMN_ORDER:
            expected = release_row[index[column]]
            actual = built[version][column]
            if actual != expected:
                differences.append(f"{version}.{column}: built {actual!r} != shipped {expected!r}")
    if differences:
        shown = "; ".join(differences[:10])
        raise ContractError(
            f"{len(differences)} transported cells disagree with the shipped release — {shown}"
        )

    return MetadataParityResult(
        compared_rows=len(frozenset(built) & frozenset(shipped)),
        compared_columns=TRANSPORT_COLUMN_ORDER,
        shipped_rows=len(shipped),
        built_rows=len(built),
        absent_from_build=tuple(sorted(absent_from_build)),
        absent_from_release=tuple(sorted(absent_from_release)),
    )


# Declared residuals live here rather than beside the rules, so the build cannot reach them at all:
# `tests/test_module_boundaries.py` forbids `derive/` from importing `oracle`. The two sets in
# `derive/metadata.py` predate this file and should move here too.
#
# `virus_group` declines on every record whose organism name cannot determine polio membership — the
# polio-containing species at species level, the bare genus, or a non-identification. Upstream
# resolved these by capsid amino-acid distance (R-MEMBERSHIP-AA-1).
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
UNRESOLVED_PARTITION_ROWS = 1596
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
UNRESOLVED_ORIGIN_ROWS = 3682
# `surveillance_stream` rows R-SURVEILLANCE-2 declines: 7,342 whose text names no surveillance
# context at all — including the 2,823 poliovirus records the release spreads across all seven of
# its values — plus those whose partition is undecided and so cannot be scoped either way. 20 of the
# 23 rescued records decline; E01570, E01572 and HV932178 carry an active `sampling_frame` decision.
UNRESOLVED_STREAM_ROWS = 8650
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
# 1,557 poliovirus records with under 300 nt of VP1 to measure divergence over, 33 with no serotype
# in the organism name to pick a Sabin reference with, and 3 whose active decision asserts a value
# outside the declared controlled vocabulary.
#
# Down 259 from 3,448, and every one of those 259 is a curated call the previous order threw away:
# the partition declined on an uninformative organism name, this rule declined for "following" it,
# and the `classification` decision stating cVDPV or wild was never read. A rule declining because a
# *weaker* signal was silent is the failure mode; see derive/partition.py.
UNRESOLVED_CLASSIFICATION_ROWS = 3189
PARTITION_FIELDS = ("virus_group", "curation_status")

# Fields the rewrite deliberately produces differently from the release. For these, requiring nine
# columns to match is the wrong gate — a superseding rule has a different `rule_id` and often a
# different `evidence_basis` on *every* row, so an equality check would report thousands of
# differences that are all intended and hide the one that is not.
#
# So the value is compared, the count of disagreements is required to equal a declared number, and
# the rule/basis columns are expected to differ. A delta that cannot be stated as a number is not a
# declared delta.
#
# Declared **per column**, not per field. An earlier version compared only `final_value` for a
# superseded field, which would have made the `locality` correction invisible: splitting one
# overstated `evidence_basis` into three honest ones changes no value at all. It would also have
# let a real regression in `source_field` or `manual_override` pass unnoticed on a superseded field.
# Every column is declared, including the zeros, so the shape of a break is legible and a new
# disagreement in an unexpected column fails.
# Which records disagree, not merely how many. Populated per column that needs it — a column whose
# declared count already equals every compared row does not, because "all of them" is an identity.
SUPERSEDED_FIELD_WITNESSES: dict[str, dict[str, str]] = {
    "collection_date": {
        "final_value": "efaafa9a6e33ff00",
        "source_field": "7f98063eac4f572e",
        "source_value": "171e028f3ca04e10",
        "evidence_basis": "449acc9d84a00427",
    },
    "collection_date_precision": {
        "final_value": "93b7f613e38ce617",
        "source_field": "9265ff07c59488ae",
        "source_value": "8c64f2ad822223f8",
        "evidence_basis": "8a4eb7836f50af41",
    },
    "collection_year_earliest": {"source_value": "5cee506fac0fac17"},
    "collection_year_latest": {"source_value": "5cee506fac0fac17"},
    "locality": {"evidence_basis": "082c3e6e214b1f23"},
    "surveillance_stream": {
        "final_value": "882f2bb66d1a407b",
        "source_value": "6cd27e18d13b5cd9",
        "manual_override": "7f1c4a18e070b024",
    },
    "sample_origin": {
        "final_value": "5e4032bf2e999dd8",
        "source_value": "868400a414c83dad",
        "manual_override": "74441f560e198627",
    },
    "specimen_type": {
        "final_value": "a8aa1248a8e83d19",
        "source_value": "39eefccaaa5b443e",
    },
    "engineered_or_construct": {
        "final_value": "b7dd84ece7a24f6e",
        "source_field": "0552a7efb840e965",
        "source_value": "aff5c1164d62f3ed",
        "manual_override": "d5c76536de115407",
    },
    "virus_type": {
        "final_value": "3ded0ff32a906ad7",
        "source_field": "5c3cae6ee684912d",
        "source_value": "3ecf43454058cfeb",
    },
    "poliovirus_classification": {
        "final_value": "2f3109db557bd43b",
        "source_value": "149a62cb6d0e0fea",
        "manual_override": "8b68cdaac2368907",
    },
}

SUPERSEDED_FIELD_DELTAS: dict[str, dict[str, int]] = {
    "collection_date": {
        # 1,761 = the 1,764 dateless records 2.4.1 gave a year recovered from outside GenBank, now
        #         emitting blank − 3 whose year an active `collection_year_curated` decision
        #         supplies. The 2,805 the release also left blank already agree. Unmoved by the
        #         membership rescue: all 15 newly-compared rows ship blank in the release too.
        "final_value": 1761,
        # Every row: a superseding rule has a different id by construction.
        "winning_rule_id": 24299,
        # All 4,564 dateless rows move to `no_date_deposited`, and their `source_value` moves with
        # it — 4,549 as before plus the 15 rescued rows, none of which deposited a date either.
        # `source_field` moves on only the 1,761 whose value also moved, because the release
        # already recorded the other 2,805 against `collection_date_precision`.
        "evidence_basis": 4564,
        "source_field": 1761,
        "source_value": 4564,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "manual_override": 0,
    },
    "collection_date_precision": {
        # 4,564 = 4,569 records that deposited no date − 2 outside the carve − 3 a ledger decision
        #         resolves to `year`, which the release also calls `year`. The gap term is 2 rather
        #         than 17 because `SEQUENCE_RESCUED_INCLUSIONS` shrank to that; the other 15 are now
        #         carved, compared, and dateless, which is why every column here moves by 15.
        "final_value": 4564,
        "winning_rule_id": 24299,
        "evidence_basis": 4564,
        "source_field": 4564,
        "source_value": 4564,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "manual_override": 0,
    },
    "sample_origin": {
        # 11,767 = 11,617 records whose `/host` names a human and which the release calls `unknown`
        #          + 149 whose `/host` names something non-human, also shipped `unknown`
        #          + 1 (`JX538031.1`) deposited as `/host=nonhuman primate` and shipped as `human`.
        # The release only curated origin for poliovirus, so `unknown` outside it means "not looked
        # at" rather than "looked at and undetermined". Curator decision 2026-07-30: where GenBank
        # states a host, read it — declining would assert non-determination about stated data.
        # 11,793 = the 11,767 above + 26 more of the same kind. The curated-classification
        #          entailment scopes 30 previously-undecided records into poliovirus, so they now
        #          read their `/host`: 26 land on `human` where the release ships `unknown` — the
        #          very disagreement the 11,617 term declares — and 4 agree outright.
        "final_value": 11793,
        # 20,625 = 20,591 + the 4 rescued records that resolve an origin at all (E01570 and E01572
        #          `vaccine`, HV932178 `human`, MA400487 `non-human`, each from an active
        #          `origin_class` decision) + the 30 the entailment brings into scope. The other 19
        #          rescued records decline and so are never compared.
        "winning_rule_id": 20625,
        "evidence_basis": 20625,
        # The rule records the input it read — the host, the specimen text, or the partition it
        # scoped by — where the release recorded the curated `origin_class` it projected. The 242
        # agreeing rows are where the host string already was the origin, plus the ledger overrides.
        "source_value": 20517,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        # 138 = the redundant `origin_class` decisions retired on 2026-07-30. The release's
        #       provenance says a human touched those cells; the rewrite no longer has an override
        #       there, because the rule derives the same value from `/host`. The *value* is
        #       unchanged — which is what `applied_unchanged` established before they were retired —
        #       so this delta is the honest consequence of retiring redundant curation, not a
        #       regression. A text rule silently overriding a live decision would also appear here,
        #       which is how that omission was caught in the first place.
        "manual_override": 138,
    },
    "collection_year_earliest": {
        # The cleanest result in the rewrite: `final_value` and `evidence_basis` both match the
        # release on all 24,284 rows, so the endpoint derivation and the basis assignment are
        # exactly what shipped. Only the superseding rule id differs everywhere, plus `source_value`
        # on the 1,763 archival-date records where the release had a year and precision is now `NA`.
        "final_value": 0,
        "evidence_basis": 0,
        "winning_rule_id": 24299,
        "source_value": 1763,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        "manual_override": 0,
    },
    "collection_year_latest": {
        "final_value": 0,
        "evidence_basis": 0,
        "winning_rule_id": 24299,
        "source_value": 1763,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        "manual_override": 0,
    },
    "surveillance_stream": {
        # 3,487 = 3,315 non-poliovirus records where the rule reads the record's own text and the
        #         release said `not_applicable`, never having curated non-polio: 2,287
        #         environmental, 917 AFP/clinical, 111 healthy/community
        #       + 92 poliovirus records whose text names BOTH a healthy contact and a poliomyelitis
        #         patient. The release says AFP/clinical; pattern order picks healthy/community.
        #         Whether a contact sampled during an AFP investigation belongs to AFP surveillance
        #         or to the community is a real question about the surveillance system, so this is a
        #         declared disagreement awaiting that call rather than a settled one.
        #       + 78 poliovirus records the release left `not_applicable`, `AFP/clinical` or
        #         `unknown` where the text names an environmental or clinical context outright.
        "final_value": 3487,
        # 15,657 = 15,654 + the 3 rescued records carrying an active `sampling_frame` decision
        #          (E01570, E01572, HV932178). The other 20 decline and are never compared.
        "winning_rule_id": 15657,
        "evidence_basis": 15657,
        "source_value": 15334,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        # 24 = the redundant `sampling_frame` decisions retired on 2026-07-30, same reasoning as
        #      `sample_origin`'s 138: the value is unchanged, the override is gone.
        "manual_override": 24,
    },
    "specimen_type": {
        # One record: GQ331952.1 deposits `/isolation_source=groundwater` and ships `stool`.
        # Groundwater is not stool, so this is left as a declared disagreement rather than
        # pattern-matched around — see `derive/epi.py`.
        "final_value": 1,
        "winning_rule_id": 11608,
        "evidence_basis": 11608,
        # 9,536 = every resolved row whose raw `/isolation_source` differs from the curated category
        #         the release recorded. R-SPECIMEN-2 records what it actually read ("throat swab"),
        #         where the release recorded the curated field it projected ("respiratory"). The
        #         remaining 2,065 agree because the qualifier already was the category ("stool").
        "source_value": 9536,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        "manual_override": 0,
    },
    # The largest deliberate delta in the rewrite, and the one with the most evidence behind it.
    # 500 = every record whose shipped TRUE the re-adjudication overturns. All 500 move TRUE ->
    #       FALSE and none move the other way, which is the check that matters: the new rule creates
    #       no TRUE the release did not already carry, it only removes ones the `\\bPAT\\b` bug
    #       invented. 498 of the 500 are patent-division deposits flagged for *where* they were
    #       deposited; the
    #       other 2 are `AJ512791`/`AJ512792`, whose ledger rows Appendix B Q8 retires.
    #
    # A 500-row flip against a shipped column needs saying plainly: this is not parity drift, it is
    # `docs/engineered-full-population-readjudication.md` landing. That report adjudicated 58 of the
    # 543 records shipping TRUE per-record; the rest flip mechanically because the predicate that
    # made them TRUE tested the database division code. The report's own headline caveat is that 468
    # of the flips carry no per-record judgement, and it stands here unchanged.
    "engineered_or_construct": {
        # 511 = 500 + 11, and both new terms are the *same* defect this delta already declares.
        #       9 are rescued patent-division records the release marked TRUE because 2.4.1's
        #       predicate read the division code as free text (E00766-9, E01570, E01572, HV932178,
        #       PE314016, PH149759); R-CONSTRUCT-2 finds no structural synthetic signal in any of
        #       them. The other 2 are `LY501105`/`LZ216100`, which this rule declined until the
        #       curator closed them FALSE on 2026-07-31 against a shipped TRUE.
        "final_value": 511,
        # Every compared row differs on both, necessarily: R-CONSTRUCT-2 is a different rule with a
        # different set of branches than the `canonical_projection` the release recorded. 24,299
        # rather than 24,282 because the 15 rescued rows are compared and the CAVA pair no longer
        # declines.
        "winning_rule_id": 24299,
        "evidence_basis": 24299,
        # The release named the curated column as its own source. R-CONSTRUCT-2 names the
        # structured field it actually read — `division` for those with no synthetic signal, the
        # digest for the ones promoted across byte-identical twins, the ledger field for the
        # curated rows.
        "source_field": 24272,
        "source_value": 24276,
        # 10, and every part is worth naming.
        #
        # Four stop being overrides: `AJ512791`, `AJ512792`, `DD214215`, `DD214221`, whose ledger
        # rows this pass retires per Appendix B Q8 and Q4.
        #
        # Six gain one — and four of those are a live D2-class defect in the release. `CS406436` and
        # `CS406482` carry an **active FALSE** `engineered_or_construct` decision and the release
        # ships them **TRUE**, with `manual_override=FALSE`: the ledger says one thing, the shipped
        # column says the other, and nothing recorded the contradiction. The `\\bPAT\\b` predicate
        # simply outvoted the curation. `LY501105`/`LZ216100`, added 2026-07-31, are the same shape
        # by design: the curator resolved them FALSE on exactly the CS406436/CS406482 precedent,
        # against a shipped TRUE.
        #
        # The other two are `CS406483` (the FALSE row corrected to TRUE here) and `PU749298` (the
        # row added here), which agree on the value and differ only in recording that a decision is
        # what reached it.
        "manual_override": 10,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
    },
    # Ten values move, and they are two different stories in equal numbers. Both are enumerated
    # because ten is small enough to enumerate and a column that types viruses should not disagree
    # anonymously.
    #
    # **Five the release ships blank while recording `manual_override=TRUE`.** `AB206350.1`
    # (`corrected_type=Coxsackievirus A18`), `M22129.1` and `M24195.1` (`confirmed_serotype=1`/`2`),
    # `S72981.1` and `S72984.1` (`confirmed_serotype=2`). The release states that a decision reached
    # the cell and then wrote nothing into it; the last two even record `evidence_basis=serotype`,
    # naming the field it projected, and ship empty anyway. Applying the decision fills five cells
    # the release left blank — the D2 lesson again, and the third distinct instance this rewrite has
    # turned up.
    #
    # **Five where the organism name states the wrong serotype and the release is right.**
    # `AY297766.1` and `AY830709.1` are both named `Human poliovirus 1 strain Sabin` and are PV3 and
    # PV2; `HM537010.1` is named `Poliovirus 2` and is PV3; `MG212473.1` and `OR208596.1` are named
    # `Poliovirus 3` and are PV2 and PV1. The release corrected each by coverage-guarded sequence
    # typing. A name-derived rule reproduces the name, and on these five the name is a mislabelled
    # deposit. This is the clearest case in the rewrite for the sequence stage: it is not a
    # disagreement about method, it is five wrong serotypes that only the sequence can catch.
    "virus_type": {
        "final_value": 10,
        "winning_rule_id": 22092,
        "evidence_basis": 22092,
        # The release named the curated column; R-TYPE-2 names `organism_name`, or the ledger field
        # when a decision won. The 93 that agree are the rows where the release also named a ledger
        # field.
        "source_field": 21999,
        "source_value": 21996,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        # Zero, and it is the one column that had to be zero: every row R-TYPE-2 reaches through the
        # ledger is a row the release also marked as overridden, including the five it then blanked.
        "manual_override": 0,
    },
    # 413 of 20,859 move, and 348 of those are one declared coarsening rather than a disagreement
    # about any record: 302 `cVDPV` and 46 `iVDPV` become the bare `VDPV`. Circulating versus
    # immunodeficient is an epidemiological attribution, no property of the sequence carries it, and
    # it is not in the record either — only 283 of the release's 1,767 `cVDPV` records name `cVDPV`
    # anywhere in their definition, strain or isolate. `VDPV` is true of every record in the band,
    # so the rule reports the band and leaves the refinement to the ledger or the queue.
    #
    # Of the remaining 65: about 40 sit at a threshold (13 `wild` -> `VDPV`, 11 `Sabin-like` ->
    # `VDPV`, 4 `wild` -> `Sabin-like`, 4 `iVDPV` -> `wild` and a scatter of ones and twos), 11 are
    # `Sabin` -> `Sabin-like` where the release distinguishes the vaccine strain itself from its
    # descendants and divergence alone cannot, and about 14 are classes the sequence does not reach
    # at all — `chimera`, `engineered/lab`, `vaccine` — which the release took from text this rule
    # does not read.
    #
    # An earlier draft disagreed on 73 further records, every one a `Sabin-like` record called
    # `wild` at 73-74% divergence, which is the unrelated-sequence expectation rather than a
    # measurement. Those records do not overlap VP1 at all and one chance 12-mer was winning the
    # diagonal vote. `MIN_DIAGONAL_ANCHORS` closed it; 2 of the 73 remain.
    "poliovirus_classification": {
        "final_value": 413,
        # 21,118 = 20,859 + the 259 records the curated-classification entailment brings into scope.
        "winning_rule_id": 21118,
        "evidence_basis": 21118,
        # Every row: the release named `classification_reconciled`, and R-CLASS-2 names the ledger
        # field or `vp1_divergence_pct`. The 1,781 agreeing on `source_value` are the curated rows,
        # where both record the asserted value itself.
        "source_field": 21118,
        "source_value": 19078,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        # 243 = the locked VDPV/wild reconciliation allowlist migrated on 2026-07-30. Those rows now
        # reach the column as decisions, where the release recorded them as `group_B_sequence_tier`
        # with no override flag — the value is the same and the attribution is not.
        "manual_override": 243,
    },
    "locality": {
        # No value moves: every blank stays blank and every non-blank was already correct. The whole
        # correction is in the branch label, which is exactly why per-column declaration matters.
        "final_value": 0,
        "winning_rule_id": 24299,
        # 19,033 = 16,987 records depositing a country and no region (now `no_admin1_deposited`)
        #          + 2,048 depositing no geo_loc_name at all (now `no_geography_deposited`),
        #          both of which 2.4.1 called `duplicate_of_admin1_suppressed`, less the 2 of those
        #          outside the carve. Measured, not arithmetic on the raw canonical counts. All 15
        #          rescued rows are patent deposits with no geography, so all 15 land here.
        "evidence_basis": 19033,
        "source_field": 0,
        "source_value": 0,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "manual_override": 0,
    },
}


@dataclass(frozen=True)
class ProvenanceParityResult:
    fields: tuple[str, ...]
    compared_rows: int
    basis_counts: dict[str, int]
    absent_from_build: int
    absent_from_release: int
    unresolved_by_field: dict[str, int]
    superseded_deltas: dict[str, dict[str, int]]


def witness_digest(triples: Iterable[str]) -> str:
    """A stable fingerprint of *which* records disagree, and how, for a superseded column."""
    joined = "\n".join(sorted(triples))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def compare_provenance_to_release(
    repository_root: Path, rows: list[dict[str, str]]
) -> ProvenanceParityResult:
    """Compare generated projection rows to the shipped provenance, on all six semantic columns.

    Comparing only `final_value` would leave the interesting half invisible. `source_field`,
    `source_value`, `winning_rule_id` and `evidence_basis` are the upstream decision tree's own
    trace; reproducing the value while getting the branch label wrong means the rule is right by
    luck, and that is exactly what has to be caught before any harder column is attempted.
    """
    header, shipped_rows = read_tsv_gz(repository_root / SHIPPED_PROVENANCE)
    if tuple(header) != PROVENANCE_COLUMNS:
        raise ContractError(
            f"{SHIPPED_PROVENANCE} columns are not the declared provenance schema: {header}"
        )
    index = {column: position for position, column in enumerate(header)}
    fields = sorted({row["canonical_field"] for row in rows})
    shipped = {
        (row[index["version"]], row[index["canonical_field"]]): row
        for row in shipped_rows
        if row[index["canonical_field"]] in set(fields)
    }

    # The provenance row set inherits the carve's declared 18-record gap exactly, and inheriting it
    # is checked rather than assumed. Skipping unmatched rows would let a rule that projected the
    # wrong population pass by producing rows nothing compares against.
    # A declined row has no shipped counterpart to compare against — the release always produced a
    # value. It is counted, required to match the declared residual, and never compared. Comparing
    # it would fail; silently dropping it would let a rule decline its way to a clean gate.
    unresolved = [row for row in rows if row.get("unresolved_reason")]
    unresolved_by_field: dict[str, int] = {}
    for row in unresolved:
        field = row["canonical_field"]
        unresolved_by_field[field] = unresolved_by_field.get(field, 0) + 1
    for field in PARTITION_FIELDS:
        if field in unresolved_by_field and unresolved_by_field[field] != UNRESOLVED_PARTITION_ROWS:
            raise ContractError(
                f"{field} declined on {unresolved_by_field[field]} records, not the declared "
                f"{UNRESOLVED_PARTITION_ROWS}; the uninformative-organism population has moved"
            )

    resolved = [row for row in rows if not row.get("unresolved_reason")]
    built_keys = {(row["version"], row["canonical_field"]) for row in resolved}
    unresolved_keys = {(row["version"], row["canonical_field"]) for row in unresolved}
    built_only = built_keys - set(shipped)
    release_only = set(shipped) - built_keys - unresolved_keys
    if {version for version, _ in built_only} != UNDECLARED_EXCLUSIONS:
        raise ContractError(
            "provenance rows with no shipped counterpart are not the declared exclusion set: "
            f"expected {sorted(UNDECLARED_EXCLUSIONS)}, got {sorted(built_only)}"
        )
    if {version for version, _ in release_only} != SEQUENCE_RESCUED_INCLUSIONS:
        raise ContractError(
            "shipped provenance rows the build does not produce are not the declared gap: "
            f"expected {sorted(SEQUENCE_RESCUED_INCLUSIONS)}, got {sorted(release_only)}"
        )

    differences: list[str] = []
    superseded_deltas: dict[str, dict[str, int]] = {}
    superseded_witnesses: dict[str, dict[str, list[str]]] = {}
    for row in resolved:
        key = (row["version"], row["canonical_field"])
        want = shipped.get(key)
        if want is None:
            continue
        field = row["canonical_field"]
        if field in SUPERSEDED_FIELD_DELTAS:
            per_column = superseded_deltas.setdefault(field, dict.fromkeys(PROVENANCE_COLUMNS, 0))
            witness = superseded_witnesses.setdefault(field, {})
            for column in PROVENANCE_COLUMNS:
                if row[column] != want[index[column]]:
                    per_column[column] += 1
                    witness.setdefault(column, []).append(
                        f"{row['version']}|{row[column]}|{want[index[column]]}"
                    )
            continue
        for column in PROVENANCE_COLUMNS:
            if row[column] != want[index[column]]:
                differences.append(
                    f"{key}.{column}: built {row[column]!r} != shipped {want[index[column]]!r}"
                )
    if differences:
        shown = "; ".join(differences[:10])
        raise ContractError(
            f"{len(differences)} provenance cells disagree with the shipped release — {shown}"
        )

    for field, expected in SUPERSEDED_FIELD_DELTAS.items():
        if field not in {row["canonical_field"] for row in resolved}:
            continue
        actual = superseded_deltas.get(field, dict.fromkeys(PROVENANCE_COLUMNS, 0))
        if set(expected) != set(PROVENANCE_COLUMNS):
            raise ContractError(
                f"the declared delta for {field} does not cover every provenance column; an "
                f"undeclared column would then be free to disagree silently"
            )
        moved = {
            c: (actual[c], expected[c])
            for c in PROVENANCE_COLUMNS
            if actual[c] != expected[c]
        }
        if moved:
            detail = "; ".join(
                f"{c}: {got} not the declared {want}" for c, (got, want) in moved.items()
            )
            raise ContractError(
                f"{field} disagrees with the release differently than declared — {detail}. A "
                f"deliberate delta has changed shape and needs re-adjudicating."
            )

        # A count alone lets one record be fixed while another regresses, keeping the total the
        # same and the gate green — demonstrated, not hypothetical. So the *identity* of the
        # disagreeing set is declared too: one hash per column over sorted version|built|shipped.
        # Columns whose declared count equals every compared row need no hash: "all of them" is
        # already an identity, and `SUPERSEDED_FIELD_WITNESSES` omits them for that reason.
        declared_witnesses = SUPERSEDED_FIELD_WITNESSES.get(field, {})
        for column, digest in declared_witnesses.items():
            actual_digest = witness_digest(superseded_witnesses.get(field, {}).get(column, []))
            if actual_digest != digest:
                raise ContractError(
                    f"{field}.{column} disagrees with the release on a different set of records "
                    f"than declared, even though the count still matches: witness {actual_digest} "
                    f"is not the declared {digest}. A substitution has been made."
                )

    # Counted over compared rows only, so the reported branch tallies sum to `compared_rows` rather
    # than silently including rows that have no shipped counterpart.
    basis_counts: dict[str, int] = {}
    for row in resolved:
        if (row["version"], row["canonical_field"]) in built_only:
            continue
        basis_counts[row["evidence_basis"]] = basis_counts.get(row["evidence_basis"], 0) + 1
    return ProvenanceParityResult(
        fields=tuple(fields),
        compared_rows=len(resolved) - len(built_only),
        basis_counts=basis_counts,
        absent_from_build=len(release_only),
        absent_from_release=len(built_only),
        unresolved_by_field=unresolved_by_field,
        superseded_deltas=superseded_deltas,
    )


def verify_metadata_parity(
    repository_root: Path, *, guarded: bool = False
) -> tuple[MetadataParityResult, ProvenanceParityResult]:
    """Rebuild the metadata transport and check both it and its provenance against the release."""
    with tempfile.TemporaryDirectory(prefix="evgc-metadata-parity-") as scratch:
        if guarded:
            run_guarded_build(repository_root, "build-metadata", Path(scratch))
            rows = read_metadata_transport(Path(scratch))
            provenance = read_projection_provenance(Path(scratch))
        else:
            built = build_metadata_layer(repository_root, Path(scratch))
            rows, provenance = built.rows, built.provenance
        return (
            compare_metadata_to_release(repository_root, rows),
            compare_provenance_to_release(repository_root, provenance),
        )
