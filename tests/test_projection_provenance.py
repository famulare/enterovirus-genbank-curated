"""Projection provenance: the rule outcomes, the basis vocabulary, and the populations behind them.

`locality` was the first column carried end to end, and doing one thoroughly before a hard one paid
off twice. It established that the rule catalog, `RuleOutcome`, the basis vocabulary and the
provenance writer all agree — on the *branch label*, not only on the value, because a rule that
reproduces the value while mislabelling which way it went is right by luck. And comparing the label
is what exposed that the shipped basis was wrong on 19,035 of 24,301 rows.

The corpus gate lives in `tests/test_metadata_transport.py`. What is here is the fast half plus the
population counts that size each deliberate break against the release.
"""

from __future__ import annotations

import csv
import gzip
from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.derive.apply import project_field
from enterovirus_genbank_curated.derive.epi import (
    UNRESOLVED_AMBIGUOUS,
    UNRESOLVED_NO_KEYWORD,
    matching_specimen_types,
    specimen_type,
)
from enterovirus_genbank_curated.derive.geo import (
    BASIS_NO_ADMIN1,
    BASIS_NO_GEOGRAPHY,
    BASIS_PARSED,
    BASIS_SUPPRESSED,
    GEO_QUALIFIER,
    unsuppressed_locality,
)
from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.derive.partition import (
    UNINFORMATIVE_ORGANISMS,
    UNRESOLVED_UNINFORMATIVE,
    curation_status,
    virus_group,
)
from enterovirus_genbank_curated.registry.implementations import load_rule_implementations
from enterovirus_genbank_curated.registry.rules import (
    RULE_IMPLEMENTATIONS,
    BoundRule,
    RuleImplementation,
    RuleSpec,
)

SHIPPED_PROVENANCE = "final/audit/canonical_projection_provenance.tsv.gz"
CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"

# Records the release labels `duplicate_of_admin1_suppressed` that had nothing to suppress: 16,987
# deposited a country and no region, 2,048 deposited no `/geo_loc_name` at all. The rewrite gives
# each its own basis; these pin the populations so the correction cannot silently change size.
SHIPPED_SUPPRESSED_WITHOUT_ADMIN1 = 16987
SHIPPED_SUPPRESSED_WITHOUT_GEOGRAPHY = 2048


def view(**qualifiers: str) -> RecordView:
    return RecordView(
        version="AB000001.1",
        accession="AB000001",
        record={"version": "AB000001.1", "accession": "AB000001"},
        qualifiers=qualifiers,
        decisions={},
    )


@pytest.fixture(scope="module")
def locality_rule() -> BoundRule:
    load_rule_implementations()
    implementation = RULE_IMPLEMENTATIONS["derive.geo.locality"]
    spec = RuleSpec(
        rule_id="R-GEO-LOCALITY-2",
        rule_version="1.0.0",
        field_name="locality",
        description="test",
        implementation=implementation.key,
        parameters={
            "no_admin1_basis": "no_admin1_deposited",
            "no_geography_basis": "no_geography_deposited",
        },
        status="active",
    )
    return BoundRule(spec=spec, implementation=implementation, pending_reason="")


@pytest.mark.parametrize(
    ("geo", "value", "basis", "source_value"),
    [
        # Three distinct reasons a locality is blank. 2.4.1 called all of them
        # `duplicate_of_admin1_suppressed`, which was true of only the third.
        ("", "", BASIS_NO_GEOGRAPHY, ""),
        ("Pakistan", "", BASIS_NO_ADMIN1, ""),
        ("Pakistan:", "", BASIS_NO_ADMIN1, ""),
        ("Pakistan: Sindh", "", BASIS_SUPPRESSED, "Sindh"),
        ("Pakistan: Sindh, Karachi", "Sindh, Karachi", BASIS_PARSED, "Sindh, Karachi"),
    ],
)
def test_the_locality_rule_reports_value_basis_and_source_value_together(
    locality_rule: BoundRule, geo: str, value: str, basis: str, source_value: str
) -> None:
    """`source_value` is the pre-suppression locality, not the raw qualifier.

    Recording the raw string would lose the distinction between "no geography was deposited" and
    "geography was deposited with no sub-admin1 detail". The release keeps that apart in
    `source_value` while conflating it in `evidence_basis`; the rewrite keeps both apart.
    """
    (row,) = project_field(locality_rule, [view(**{GEO_QUALIFIER: geo})])
    assert row["final_value"] == value
    assert row["evidence_basis"] == basis
    assert row["source_value"] == source_value
    assert row["source_field"] == "location_genbank"
    assert row["winning_rule_id"] == "R-GEO-LOCALITY-2"
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


def partition_view(organism: str, **decisions: str) -> RecordView:
    return RecordView(
        version="AB000001.1",
        accession="AB000001",
        record={"version": "AB000001.1", "accession": "AB000001", "organism_name": organism},
        qualifiers={},
        decisions=decisions,
    )


@pytest.mark.parametrize(
    ("organism", "group"),
    [
        ("Poliovirus 1", "poliovirus"),
        ("Human poliovirus 2", "poliovirus"),
        ("Coxsackievirus A24", "non_polio_enterovirus"),
        ("Enterovirus B", "non_polio_enterovirus"),
        ("Enterovirus D68", "non_polio_enterovirus"),
    ],
)
def test_a_type_level_organism_name_decides_membership(organism: str, group: str) -> None:
    outcome = virus_group({"groups": ["poliovirus", "non_polio_enterovirus"]},
                          partition_view(organism))
    assert outcome.value == group
    assert outcome.resolved
    assert not outcome.manual_override


@pytest.mark.parametrize("organism", sorted(UNINFORMATIVE_ORGANISMS))
def test_an_uninformative_organism_name_declines(organism: str) -> None:
    """The whole point of the rule.

    Every one of these names is either the species that contains poliovirus, the bare genus, or not
    a virus identification at all. Defaulting them to non-polio would score 98.3% against the
    release and be a guess on 414 records — and four downstream columns would inherit it.
    """
    outcome = virus_group({"groups": ["poliovirus", "non_polio_enterovirus"]},
                          partition_view(organism))
    assert not outcome.resolved
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_UNINFORMATIVE


@pytest.mark.parametrize(("asserted", "group"), [("TRUE", "poliovirus"),
                                                 ("FALSE", "non_polio_enterovirus")])
def test_a_ledger_decision_resolves_an_uninformative_name_and_is_recorded(
    asserted: str, group: str
) -> None:
    """A decision that reached the value has to say so, or `manual_override` is decoration."""
    outcome = virus_group(
        {"groups": ["poliovirus", "non_polio_enterovirus"]},
        partition_view("Enterovirus C", is_poliovirus=asserted),
    )
    assert outcome.value == group
    assert outcome.manual_override


def test_a_ledger_decision_beats_the_name_predicate() -> None:
    """Curation the text overrides is curation that does not exist — the D2 failure."""
    outcome = virus_group(
        {"groups": ["poliovirus", "non_polio_enterovirus"]},
        partition_view("Poliovirus 2", is_poliovirus="FALSE"),
    )
    assert outcome.value == "non_polio_enterovirus"
    assert outcome.manual_override


def test_curation_status_follows_the_partition_without_claiming_an_override() -> None:
    """The curator adjudicated membership, not the vouching policy that follows from it."""
    parameters = {
        "poliovirus_status": "vouched",
        "non_poliovirus_status": "provisional",
        "carve_excluded_status": "excluded",
    }
    vouched = curation_status(parameters, partition_view("Enterovirus C", is_poliovirus="TRUE"))
    assert vouched.value == "vouched"
    assert not vouched.manual_override
    assert curation_status(parameters, partition_view("Echovirus 6")).value == "provisional"
    assert not curation_status(parameters, partition_view("unidentified")).resolved


@pytest.mark.slow
def test_the_shipped_locality_basis_conflates_three_populations(repository_root: Path) -> None:
    """Sizes the correction against the release, so it cannot silently change shape.

    The release has two locality bases; the rewrite has four. This pins what the shipped
    `duplicate_of_admin1_suppressed` actually contained, which is the evidence for splitting it: of
    23,268 rows, only 4,233 were suppressions.
    """
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
        canonical = list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))
    no_geography = {row["version"] for row in canonical if not row["country"]}
    no_admin1 = {row["version"] for row in canonical if row["country"] and not row["admin1"]}

    assert len(no_geography) == SHIPPED_SUPPRESSED_WITHOUT_GEOGRAPHY
    assert len(no_admin1) == SHIPPED_SUPPRESSED_WITHOUT_ADMIN1
    # Every one of those 19,035 ships as a suppression, and none of them suppressed anything.
    overstated = no_geography | no_admin1
    assert all(
        row["evidence_basis"] == BASIS_SUPPRESSED
        for row in locality_rows
        if row["version"] in overstated
    )
    genuine = len(locality_rows) - len(overstated) - 1033
    assert genuine == 4233


# --- specimen_type: the keyword rule, and the two defects its disagreements exposed --------------

SPECIMEN_PATTERNS = {
    "environmental": "sewage|wastewater|waste water|effluent|water|environmental",
    "stool": "stool|faeces|faecal|feces|fecal|rectal",
    "respiratory": "throat|nasal|nasopharyn|oropharyn|respiratory|sputum|pharyn",
    "CNS": r"\bcsf\b|cerebrospinal",
    "serum": "serum|blood|plasma",
}


@pytest.mark.parametrize(
    ("isolation_source", "expected"),
    [
        ("stool", {"stool"}),
        ("Stool specimen from AFP case", {"stool"}),
        ("feces", {"stool"}),
        ("sewage", {"environmental"}),
        ("wastewater", {"environmental"}),
        ("river water", {"environmental"}),
        ("nasopharyngeal/oropharyngeal swab", {"respiratory"}),
        ("CSF", {"CNS"}),
        ("", set()),
        ("conjunctival swab", set()),
        ("rhabdomyosarcoma cell", set()),
        # The word-boundary defect: a bare `fec` fires inside "infection", so two records labelled
        # only with a respiratory illness were being called stool.
        ("case of acute respiratory infection", {"respiratory"}),
        # Genuine ambiguity: the source names two specimens, so no single answer is derivable.
        ("throat swab and stool samples from an immunodeficient patient", {"respiratory", "stool"}),
    ],
)
def test_specimen_keywords_match_every_category_present(
    isolation_source: str, expected: set[str]
) -> None:
    assert matching_specimen_types(SPECIMEN_PATTERNS, isolation_source) == expected


def specimen_view(isolation_source: str) -> RecordView:
    return RecordView(
        version="AB000001.1",
        accession="AB000001",
        record={"version": "AB000001.1", "accession": "AB000001"},
        qualifiers={"isolation_source": isolation_source},
        decisions={},
    )


def test_two_specimen_keywords_decline_rather_than_pick_by_pattern_order() -> None:
    """The whole reason `matching_specimen_types` returns a set.

    Iteration order would give a confident answer here and be right or wrong by accident. Four
    records in the corpus name both a throat swab and a stool sample.
    """
    outcome = specimen_type(
        {"patterns": SPECIMEN_PATTERNS},
        specimen_view("throat swab and stool samples from an immunodeficient patient"),
    )
    assert not outcome.resolved
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_AMBIGUOUS


def test_no_keyword_declines_and_keeps_what_it_read() -> None:
    outcome = specimen_type({"patterns": SPECIMEN_PATTERNS}, specimen_view("conjunctival swab"))
    assert not outcome.resolved
    assert outcome.unresolved_reason == UNRESOLVED_NO_KEYWORD
    # `source_value` records the qualifier even when the rule declines, so a queue row can show the
    # curator what the rule was looking at.
    assert outcome.source_value == "conjunctival swab"
