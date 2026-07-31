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
# 1,832 = 1,765 records carrying an uninformative organism name in the shipped canonical table
#         − 17 that are `SEQUENCE_RESCUED_INCLUSIONS` and so are not in the carve at all
#         − 15 carved ones the ledger's `is_poliovirus` decisions resolve
#              (17 such decisions exist; 2 are on records literally named `Poliovirus 2`/`3`, which
#               the name predicate already decides, so only 15 land on uninformative names)
#         + 99 a review found were being guessed: 95 named `Human enterovirus`, the unqualified
#           pre-2016 species name, and 4 named for a strain rather than a type.
UNRESOLVED_PARTITION_ROWS = 1832
# `specimen_type` rows R-SPECIMEN-2 declines, over the built carve: those where no keyword matches
# `/isolation_source` and 4 where two categories match, naming two specimens rather than one. One of
# the 12,680 is AF326751.2, which the release excludes, so 12,683 of the 24,284 shared rows decline.
UNRESOLVED_SPECIMEN_ROWS = 12677
# `sample_origin` rows R-ORIGIN-2 declines, over the built carve: poliovirus records that
# deposited neither a `/host` nor a recognisable human specimen, plus those whose partition is
# itself undecided and so cannot be scoped either way.
UNRESOLVED_ORIGIN_ROWS = 4582
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
        "source_value": "fc9f7ef2a78df8bd",
        "evidence_basis": "26f98ff5bbd3f6a2",
    },
    "collection_date_precision": {
        "final_value": "b044d2c0f1dd8b35",
        "source_field": "24fdd1bf1b32ca05",
        "source_value": "d248b53f82e488c2",
        "evidence_basis": "7e6522502070b4fb",
    },
    "locality": {"evidence_basis": "8c042f23e8b20cd4"},
    "sample_origin": {
        "final_value": "2e915e4fd4f6f397",
        "source_value": "8753f4cb19e1dccb",
    },
    "specimen_type": {
        "final_value": "a8aa1248a8e83d19",
        "source_value": "39eefccaaa5b443e",
    },
}

SUPERSEDED_FIELD_DELTAS: dict[str, dict[str, int]] = {
    "collection_date": {
        # 1,761 = the 1,764 dateless records 2.4.1 gave a year recovered from outside GenBank, now
        #         emitting blank − 3 whose year an active `collection_year_curated` decision
        #         supplies. The 2,805 the release also left blank already agree.
        "final_value": 1761,
        # Every row: a superseding rule has a different id by construction.
        "winning_rule_id": 24284,
        # All 4,549 dateless rows move to `no_date_deposited`, and their `source_value` moves with
        # it. `source_field` moves on only the 1,761 whose value also moved, because the release
        # already recorded the other 2,805 against `collection_date_precision`.
        "evidence_basis": 4549,
        "source_field": 1761,
        "source_value": 4549,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "manual_override": 0,
    },
    "collection_date_precision": {
        # 4,549 = 4,569 records that deposited no date − 17 outside the carve − 3 a ledger decision
        #         resolves to `year`, which the release also calls `year`.
        "final_value": 4549,
        "winning_rule_id": 24284,
        "evidence_basis": 4549,
        "source_field": 4549,
        "source_value": 4549,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "manual_override": 0,
    },
    "sample_origin": {
        # Only four, and each is explicable. JX181922.1 and OR538735.1 are records the ledger calls
        # non-poliovirus that the release nonetheless gave a curated origin, where R-ORIGIN-2 scopes
        # them out. JX538031.1 deposits `/host=nonhuman primate` and the release calls it `human`,
        # which is simply wrong. MK719554.1 is the authorized correction: `/host=Homo sapiens`
        # against a shipped `unknown`.
        "final_value": 4,
        "winning_rule_id": 19702,
        "evidence_basis": 19702,
        # The rule records the input it read — the host, the specimen text, or the partition it
        # scoped by — where the release recorded the curated `origin_class` it projected. The 242
        # agreeing rows are where the host string already was the origin, plus the ledger overrides.
        "source_value": 19460,
        "accession": 0,
        "version": 0,
        "canonical_field": 0,
        "source_field": 0,
        # Exact: TRUE on precisely the records an active `origin_class` decision resolves. A text
        # rule overriding the ledger shows up here, which is how the omission was caught.
        "manual_override": 0,
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
    "locality": {
        # No value moves: every blank stays blank and every non-blank was already correct. The whole
        # correction is in the branch label, which is exactly why per-column declaration matters.
        "final_value": 0,
        "winning_rule_id": 24284,
        # 19,018 = 16,987 records depositing a country and no region (now `no_admin1_deposited`)
        #          + 2,048 depositing no geo_loc_name at all (now `no_geography_deposited`),
        #          both of which 2.4.1 called `duplicate_of_admin1_suppressed`, less the 17 of those
        #          outside the carve. Measured, not arithmetic on the raw canonical counts.
        "evidence_basis": 19018,
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
