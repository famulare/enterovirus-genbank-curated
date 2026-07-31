"""Pipeline stages that regenerate release artifacts from `raw/`.

Two stages exist so far, and they are reproducible to different depths.

The **source layer** is complete: `raw/sequence.gb.zip` in, twelve normalized relations out,
byte-identical to the shipped release, with no registry, no curated master, no network, and no path
outside the clone.

The **canonical metadata transport** is partial by construction and says so. It carves the canonical
row set and fills the thirteen columns whose value is a source value; the other thirteen need the
curated master or a sequence-comparison stage that does not exist here yet. See
`derive/metadata.py`.

Nothing here reads `final/`. The comparisons against the shipped release live in
`oracle/parity.py`, and `sandbox.install_input_guard` refuses a `final/` read outright, so that
separation is a property of the runtime rather than of this docstring.
"""

from __future__ import annotations

import tempfile
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from enterovirus_genbank_curated.contracts import (
    DECISIONS_LEDGER_PATH,
    DECISIONS_SCHEMA_PATH,
    PARITY_SPEC_PATH,
    RULES_SCHEMA_PATH,
    ContractError,
    load_decision_contract,
    validate_decision_ledger,
    validate_parity_spec,
    verify_raw_input,
)
from enterovirus_genbank_curated.curate.apply import (
    DecisionApplication,
    apply_decisions,
    assert_every_decision_is_accounted_for,
    project_without_decisions,
)
from enterovirus_genbank_curated.curate.queue import build_queue
from enterovirus_genbank_curated.derive.apply import build_record_views, project_field
from enterovirus_genbank_curated.derive.evidence import (
    measure_membership_rescue,
    measure_sequence_evidence,
)
from enterovirus_genbank_curated.derive.metadata import transport_metadata
from enterovirus_genbank_curated.export.audit import (
    write_decision_applications,
    write_membership_rescue,
    write_projection_provenance,
    write_rules_view,
    write_vp1_divergence,
)
from enterovirus_genbank_curated.export.canonical import (
    assemble_canonical_rows,
    write_canonical_table,
)
from enterovirus_genbank_curated.export.metadata import write_metadata_transport
from enterovirus_genbank_curated.export.queue import write_curation_queue
from enterovirus_genbank_curated.export.release import write_release_manifests
from enterovirus_genbank_curated.export.source import (
    write_source_relational,
    write_source_tsv,
)
from enterovirus_genbank_curated.genbank.parse import parse_source_tables, read_sequences
from enterovirus_genbank_curated.registry.decisions import (
    load_active_decisions,
    load_excluded_accessions,
    load_ledger_rows,
)
from enterovirus_genbank_curated.registry.implementations import load_rule_implementations
from enterovirus_genbank_curated.registry.rules import (
    RULES_CATALOG_PATH,
    bind_rules,
    load_rule_catalog,
    load_rule_contract,
)
from enterovirus_genbank_curated.validation.invariants import (
    assert_date_precision_invariant,
    assert_locality_basis_invariant,
)

IMMUTABLE_DIRS = ("final", "raw")

# The rule whose parameters decide carve membership for records the GenBank lineage rejects. Looked
# up in the catalog rather than hardcoded here, so its thresholds stay declared data.
MEMBERSHIP_RULE_ID = "R-MEMBERSHIP-AA-1"


@dataclass(frozen=True)
class SourceBuildResult:
    row_counts: dict[str, int]
    output_dir: Path


def _same_file(a: Path, b: Path) -> bool:
    """Identity by inode, so a case-insensitive filesystem cannot disguise the same directory."""
    try:
        return a.stat().st_dev == b.stat().st_dev and a.stat().st_ino == b.stat().st_ino
    except OSError:
        return False


def reject_immutable_output(repository_root: Path, output_dir: Path) -> None:
    """Refuse to build into the shipped release.

    Path equality is not enough. On a case-insensitive filesystem `final/SOURCE` resolves to a
    different string but the *same inode* as `final/source`, so an equality check waves it through
    and the build overwrites all twelve shipped tables. Containment is checked against every
    immutable tree, by resolved path and by inode, for the target and each of its parents.
    """
    root = repository_root.resolve()
    target = output_dir.resolve()
    for name in IMMUTABLE_DIRS:
        protected = (root / name).resolve()
        if not protected.exists():
            continue
        candidates = [target, *target.parents]
        if target.is_relative_to(protected) or any(_same_file(c, protected) for c in candidates):
            raise ContractError(
                f"refusing to write into {name}/: it is an immutable parity target, not a build "
                f"destination (resolved output {target})"
            )


@contextmanager
def extracted_flat_file(repository_root: Path) -> Iterator[Path]:
    """Authenticate the frozen archive, then stream its declared member to a temp file.

    Authentication is not optional and not a warning: `verify_raw_input` re-hashes the archive and
    the member before anything is parsed, so a corrupted or substituted input fails closed here
    rather than producing a plausible-looking release.
    """
    spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
    raw = spec["raw_input"]
    verify_raw_input(repository_root, raw)

    member = raw["archive_member"]
    if Path(member).is_absolute() or ".." in Path(member).parts:
        raise ContractError(f"refusing to extract a member with a traversing name: {member!r}")

    with tempfile.TemporaryDirectory(prefix="evgc-raw-") as scratch:
        target = Path(scratch) / member
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            zipfile.ZipFile(repository_root / raw["path"]) as archive,
            archive.open(member) as source,
            target.open("wb") as sink,
        ):
            while chunk := source.read(1 << 22):
                sink.write(chunk)
        yield target


def parse_authenticated_source(repository_root: Path) -> dict[str, list[dict[str, str]]]:
    """Parse the frozen archive and refuse a corpus that is not the size the contract declares.

    The archive is hash-authenticated, so its record count is a known quantity. Not checking it
    meant a non-GenBank or empty input produced twelve header-only tables and exited 0.
    """
    spec = validate_parity_spec(repository_root / PARITY_SPEC_PATH)
    expected_records = spec["raw_input"]["record_count"]

    with extracted_flat_file(repository_root) as flat_file:
        tables = parse_source_tables(flat_file)

    actual_records = len(tables["records"])
    if actual_records != expected_records:
        raise ContractError(
            f"parsed {actual_records} records but the authenticated archive declares "
            f"{expected_records}"
        )
    return tables


def build_source_layer(
    repository_root: Path, output_dir: Path, *, relational: bool = True
) -> SourceBuildResult:
    """Regenerate `source/` from the frozen archive alone."""
    reject_immutable_output(repository_root, output_dir)
    tables = parse_authenticated_source(repository_root)
    counts = write_source_tsv(output_dir, tables)
    if relational:
        write_source_relational(output_dir)
    return SourceBuildResult(row_counts=counts, output_dir=output_dir)


@dataclass(frozen=True)
class MetadataBuildResult:
    rows: list[dict[str, str]]
    provenance: list[dict[str, str]]
    applications: list[DecisionApplication]
    application_tally: dict[str, int]
    row_counts: dict[str, int]
    output_dir: Path


def build_metadata_layer(repository_root: Path, output_dir: Path) -> MetadataBuildResult:
    """Carve the canonical row set and transport every transportable column into it.

    The ledger is validated before it is used, not after. `load_excluded_accessions` reads three
    columns and would happily accept a ledger with a duplicate active assertion or an out-of-range
    status, which is exactly the input that should stop a build rather than shape one.
    """
    reject_immutable_output(repository_root, output_dir)
    contract = load_decision_contract(repository_root / DECISIONS_SCHEMA_PATH)
    ledger_path = repository_root / DECISIONS_LEDGER_PATH
    validate_decision_ledger(ledger_path, contract)
    excluded = load_excluded_accessions(ledger_path)

    tables = parse_authenticated_source(repository_root)

    load_rule_implementations()
    rule_contract = load_rule_contract(repository_root / RULES_SCHEMA_PATH)
    catalog = load_rule_catalog(repository_root / RULES_CATALOG_PATH, rule_contract)

    # Sequences are read before the carve, because the carve now depends on them: R-MEMBERSHIP-AA-1
    # decides membership for the records whose GenBank lineage does not name the genus. Reading the
    # flat file a second time is the cost of keeping `records` at its shipped twelve columns — see
    # `genbank/parse.read_sequences`.
    with extracted_flat_file(repository_root) as flat_file:
        sequences = read_sequences(flat_file)

    membership = next(spec for spec in catalog if spec.rule_id == MEMBERSHIP_RULE_ID)
    rescued = measure_membership_rescue(tables, sequences, excluded, membership.parameters)
    transport = transport_metadata(tables, excluded, frozenset(rescued))

    # Provenance for every canonical field whose rule is implemented, over the carved rows only. The
    # value and its provenance row come from the same `RuleOutcome`, so a canonical value without a
    # provenance row is not expressible — boundary 5 held structurally rather than by convention.
    evidence = measure_sequence_evidence(tables, sequences, transport.rows)

    views = build_record_views(
        tables,
        (row["version"] for row in transport.rows),
        load_active_decisions(ledger_path),
        evidence,
    )
    bound = bind_rules(catalog)
    provenance = [
        row
        for rule in bound.values()
        if rule.implementation is not None
        for row in project_field(rule, views)
    ]

    # Cross-column invariants, before anything is written. A rule can be individually right and the
    # table still incoherent, and no single rule can see two columns.
    not_applicable_dates = assert_date_precision_invariant(provenance)
    locality_bases = assert_locality_basis_invariant(provenance, transport.rows)

    # Every declined cell becomes exactly one queue row, grouped by the input the rule could not
    # decide from. A rule that declines has done its job; the value still has to come from a
    # curator.
    queue = build_queue(provenance)

    # What became of every recorded decision, measured against a counterfactual projection with the
    # ledger withheld. Without that second projection, "this decision changed something" is an
    # assumption; with it, `applied_unchanged` also surfaces curation a rule has made redundant.
    ledger_rows = load_ledger_rows(ledger_path)
    applications = apply_decisions(
        ledger=ledger_rows,
        provenance=provenance,
        counterfactual=project_without_decisions(list(bound.values()), views),
        corpus_accessions=frozenset(row["accession"] for row in tables["records"]),
        carved_versions={row["accession"]: row["version"] for row in transport.rows},
    )
    application_tally = assert_every_decision_is_accounted_for(ledger_rows, applications)

    row_counts = {
        "source_records": len(tables["records"]),
        "transported": len(transport.rows),
        "excluded_by_ledger": transport.excluded_by_ledger,
        "excluded_as_non_enterovirus": transport.excluded_as_non_enterovirus,
        "included_by_membership_rescue": transport.included_by_membership_rescue,
        "provenance_rows": len(provenance),
        "dates_not_applicable": not_applicable_dates,
        "localities_without_geography": locality_bases.get("no_geography_deposited", 0),
        "curation_queue_groups": len(queue),
        "decision_applications": len(applications),
        "curation_queue_records": sum(len(group.versions) for group in queue),
    }
    # The canonical table itself: all 26 columns, transported plus projected, one row per carved
    # record. This is the artifact a consumer wants; the transport and provenance beside it are how
    # the artifact is checked.
    canonical = assemble_canonical_rows(transport.rows, provenance)
    row_counts.update(write_canonical_table(output_dir, canonical, sequences))

    # Two audit views the pipeline could already produce and no build wrote, so every release so far
    # shipped an `audit/` directory missing them.
    #
    # The rule view is the sharper omission: it comes out byte-identical to the release's own
    # `rules.tsv.gz`, and only one test ever called it, which proved the writer and not the release.
    # A rule catalog a release does not carry is a catalog a consumer has to take on trust.
    #
    # The VP1 divergence view was worse than absent — it was computed on every build, used by
    # R-CLASS-2 to decide `poliovirus_classification`, and then discarded, so the release published
    # verdicts and withheld the measurements behind them.
    row_counts["rules_in_baseline_view"] = write_rules_view(output_dir, catalog)
    # Was `vp1_measured`, the length of an in-memory dict. Renamed because the number now counts
    # rows in an artifact a reader can open, which is the only form of a count that can be checked.
    row_counts["vp1_divergence_rows"] = write_vp1_divergence(output_dir, evidence)

    # Both counts go in before this call, because `write_metadata_transport` snapshots `row_counts`
    # into the coverage JSON. A key added after it would reach the build manifest and not the
    # coverage declaration, and two artifacts disagreeing about the same build is exactly the defect
    # the coverage declaration exists to prevent.
    write_metadata_transport(output_dir, transport.rows, row_counts, provenance)
    write_projection_provenance(output_dir, provenance)
    write_curation_queue(output_dir, queue)
    write_decision_applications(output_dir, applications)
    write_membership_rescue(output_dir, rescued, tables["records"])

    # Last, because the file manifest hashes everything above it. A build that failed before here
    # leaves artifacts with no manifest, which is the right way round: an unstamped directory is
    # visibly not a release, where a manifest written first would describe a release that does not
    # exist.
    write_release_manifests(
        output_dir,
        repository_root,
        rows=canonical,
        provenance=provenance,
        row_counts=row_counts,
        application_tally=application_tally,
        raw_input=validate_parity_spec(repository_root / PARITY_SPEC_PATH)["raw_input"],
    )
    return MetadataBuildResult(
        rows=transport.rows,
        provenance=provenance,
        applications=applications,
        application_tally=application_tally,
        row_counts=row_counts,
        output_dir=output_dir,
    )


