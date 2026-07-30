"""Projection provenance, proved end to end on `locality`.

The point of doing one column this thoroughly before attempting a hard one: it establishes that the
rule catalog, `RuleOutcome`, the basis vocabulary and the provenance writer all agree with the
release, on the *branch label* and not only on the value. A rule that reproduces the value while
mislabelling which way it went is right by luck, and nothing downstream would notice.

The corpus gate lives in `tests/test_metadata_transport.py`, which compares all nine shipped
columns for every shared record. What is here is the fast half: the outcome invariants, the basis
vocabulary, and the shipped population counts worth pinning.
"""

from __future__ import annotations

import csv
import gzip
from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.apply import project_field
from enterovirus_genbank_curated.derive.geo import (
    BASIS_PARSED,
    BASIS_SUPPRESSED,
    GEO_QUALIFIER,
    unsuppressed_locality,
)
from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.implementations import load_rule_implementations
from enterovirus_genbank_curated.registry.rules import (
    RULE_IMPLEMENTATIONS,
    BoundRule,
    RuleImplementation,
    RuleSpec,
)

SHIPPED_PROVENANCE = "final/audit/canonical_projection_provenance.tsv.gz"
CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"

# Records with no `/geo_loc_name` at all, which the release nonetheless labels
# `duplicate_of_admin1_suppressed` — there was never a locality to suppress. Pinned so the
# infelicity stays visible rather than being quietly inherited forever. See `derive/geo.py`.
NOTHING_TO_SUPPRESS = 2048


def view(**qualifiers: str) -> RecordView:
    return RecordView(
        version="AB000001.1",
        accession="AB000001",
        record={"version": "AB000001.1", "accession": "AB000001"},
        qualifiers=qualifiers,
    )


@pytest.fixture(scope="module")
def locality_rule() -> BoundRule:
    load_rule_implementations()
    implementation = RULE_IMPLEMENTATIONS["derive.geo.locality"]
    spec = RuleSpec(
        rule_id="R-GEO-LOCALITY-1",
        rule_version="2.4.1",
        field_name="locality",
        description="test",
        implementation=implementation.key,
        parameters={},
        status="active",
    )
    return BoundRule(spec=spec, implementation=implementation, pending_reason="")


@pytest.mark.parametrize(
    ("geo", "value", "basis", "source_value"),
    [
        ("", "", BASIS_SUPPRESSED, ""),
        ("Pakistan", "", BASIS_SUPPRESSED, ""),
        ("Pakistan: Sindh", "", BASIS_SUPPRESSED, "Sindh"),
        ("Pakistan: Sindh, Karachi", "Sindh, Karachi", BASIS_PARSED, "Sindh, Karachi"),
    ],
)
def test_the_locality_rule_reports_value_basis_and_source_value_together(
    locality_rule: BoundRule, geo: str, value: str, basis: str, source_value: str
) -> None:
    """`source_value` is the pre-suppression locality, not the raw qualifier.

    Recording the raw string would lose the distinction between "no geography was deposited" and
    "geography was deposited with no sub-admin1 detail" — the release keeps them apart and so must
    this.
    """
    (row,) = project_field(locality_rule, [view(**{GEO_QUALIFIER: geo})])
    assert row["final_value"] == value
    assert row["evidence_basis"] == basis
    assert row["source_value"] == source_value
    assert row["source_field"] == "location_genbank"
    assert row["winning_rule_id"] == "R-GEO-LOCALITY-1"
    assert row["manual_override"] == "FALSE"


def test_an_undeclared_evidence_basis_is_refused(locality_rule: BoundRule) -> None:
    """What makes declaring `evidence_bases` worth doing.

    Without this the basis column is free text, and a rule could write a value that appears in no
    vocabulary — which is how a controlled-vocabulary column stops being one.
    """
    rogue = RuleImplementation(
        key=locality_rule.implementation.key,
        required_parameters=frozenset(),
        declared_bases=locality_rule.implementation.declared_bases,
        fn=lambda parameters, v: RuleOutcome(
            value="x", evidence_basis="invented", source_field="f", source_value="s"
        ),
    )
    bound = BoundRule(spec=locality_rule.spec, implementation=rogue, pending_reason="")
    with pytest.raises(ContractError, match="does not declare"):
        project_field(bound, [view()])


def test_a_pending_rule_cannot_project(locality_rule: BoundRule) -> None:
    bound = BoundRule(spec=locality_rule.spec, implementation=None, pending_reason="not written")
    with pytest.raises(ContractError, match="cannot project"):
        project_field(bound, [view()])


def test_an_unresolved_outcome_may_not_carry_a_value() -> None:
    """The invariant that keeps "unresolved" from becoming a guess with a note attached."""
    with pytest.raises(ValueError, match="must not carry a value"):
        RuleOutcome(
            value="Sindh",
            evidence_basis=BASIS_PARSED,
            source_field="location_genbank",
            source_value="Sindh",
            unresolved_reason="no_source_signal",
        )


def test_unsuppressed_locality_keeps_the_whole_remainder() -> None:
    assert unsuppressed_locality("Congo: Kinshasa: Limete") == "Kinshasa: Limete"
    assert unsuppressed_locality("Congo") == ""


@pytest.mark.slow
def test_the_shipped_basis_split_is_what_the_rule_reproduces(repository_root: Path) -> None:
    """Both shipped branch populations, and the 2,048 rows whose basis label overstates its case."""
    with gzip.open(repository_root / SHIPPED_PROVENANCE, "rt", newline="") as handle:
        locality_rows = [
            row
            for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            if row["canonical_field"] == "locality"
        ]
    assert Counter(r["evidence_basis"] for r in locality_rows) == Counter(
        {BASIS_SUPPRESSED: 23268, BASIS_PARSED: 1033}
    )

    # A blank canonical `country` means no `/geo_loc_name` was deposited at all — the qualifier's
    # presence and a non-blank country coincide exactly across the corpus. `source_value` will not
    # do here: it is also blank for a country-only string like `China`, which did deposit geography.
    with gzip.open(repository_root / CANONICAL_METADATA, "rt", newline="") as handle:
        no_geography = {
            row["version"]
            for row in csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL)
            if not row["country"]
        }
    assert len(no_geography) == NOTHING_TO_SUPPRESS
    assert all(
        row["evidence_basis"] == BASIS_SUPPRESSED
        for row in locality_rows
        if row["version"] in no_geography
    )
