"""`R-TYPE-2`: the organism name, the definition line, and the traps in both.

This rule had **no unit test at all** until 2026-08-12, and its docstring names four organism-name
traps — `Human poliovirus 30/ROU/2008`, `Enterovirus 103`, `Enterovirus J115`, `Human rhinovirus 1A`
— none of which was asserted anywhere. A trap documented and not tested is a comment, so each is a
case below, with the name it was found on.

The definition-line reading added the same week brings its own, and one of them is a defect the
frozen upstream stage shipped: the bare `CA13` form has no anchoring word, so `USA-CA08-10869` — a
California 2008 strain designation — reads as Coxsackievirus A8. Seven records, six of which 2.4.1
types `CVB1`.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.derive.typing import (
    BASIS_LEDGER,
    BASIS_SEROTYPE_NAME,
    BASIS_TYPE_DEFINITION,
    BASIS_TYPE_NAME,
    UNRESOLVED_CURATED_UNKNOWN,
    UNRESOLVED_NO_TYPE_IN_NAME,
    type_from_definition,
    type_from_name,
    virus_type,
)
from enterovirus_genbank_curated.export.metadata import read_projection_provenance

RECOVERED_FROM_DEFINITION = 427
DECLINED_ROWS = 1789


def view(
    organism: str = "", definition: str = "", decisions: dict[str, str] | None = None
) -> RecordView:
    return RecordView(
        version="X00001.1",
        accession="X00001",
        record={"organism_name": organism, "definition": definition},
        qualifiers={},
        decisions=decisions or {},
    )


def typed(organism: str = "", definition: str = "", **decisions: str):
    return virus_type({}, view(organism, definition, decisions or None))


# --- the organism-name convention ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("organism", "expected"),
    [
        ("Poliovirus 1", "PV1"),
        ("Human poliovirus 2 strain Sabin", "PV2"),
        ("Human poliovirus type 3", "PV3"),
        ("Coxsackievirus A24", "CVA24"),
        ("Human coxsackievirus A21 Coe", "CVA21"),
        ("Echovirus E11", "E11"),
        ("Echovirus 30", "E30"),
        ("Enterovirus A71", "EV-A71"),
        ("enterovirus D68", "EV-D68"),
        ("rhinovirus C40", "RV-C40"),
        # Everything after the number is not part of the type.
        ("Human coxsackievirus A20a", "CVA20"),
        ("rhinovirus A1B", "RV-A1"),
        ("Human coxsackievirus A24v Marseille/2012/1", "CVA24"),
    ],
)
def test_the_organism_name_convention(organism: str, expected: str) -> None:
    assert type_from_name(organism) == expected


@pytest.mark.parametrize(
    ("organism", "why"),
    [
        # The docstring's four traps, each a real name in this corpus.
        ("Human poliovirus 30/ROU/2008", "the 30 is an isolate number, and this record is PV2"),
        ("Enterovirus 103", "the pre-2016 bare numbering carries no species letter"),
        ("Enterovirus J115", "J is a simian species; the human scheme runs A to D"),
        ("Human rhinovirus 1A", "digits-then-letter is the old serial numbering"),
        # The three bare species names, which is the whole reason the name-derived split is clean.
        ("Enterovirus A", "a species name states no type"),
        ("Enterovirus B", "a species name states no type"),
        ("Enterovirus C", "a species name states no type"),
        # And the four the docstring names as consequences of declining rather than guessing.
        ("Enterovirus coxsackiepol", "a chimera label with no serotype in it"),
        ("synthetic construct", "no name to read"),
        ("unidentified poliovirus", "poliovirus without a serotype"),
        ("Human poliovirus sp.", "no serotype stated"),
    ],
)
def test_a_name_that_states_no_type_states_no_type(organism: str, why: str) -> None:
    assert type_from_name(organism) == "", why


def test_the_serotype_digit_is_anchored_and_that_is_what_saves_pv2() -> None:
    """`Human poliovirus 30/ROU/2008` is the record the `(?![0-9])` exists for.

    Without it the rule reads `3` and ships PV3 on a PV2 record — a wrong determination under a rule
    that looks right, which is worse than a decline.
    """
    outcome = typed(organism="Human poliovirus 30/ROU/2008")
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_NO_TYPE_IN_NAME


def test_the_genus_form_outranks_the_species_form() -> None:
    """`Coxsackievirus A24` must not become `EV-A24`; the vocabulary uses the genus spelling."""
    assert type_from_name("Human coxsackievirus A24, Enterovirus C") == "CVA24"


# --- the definition-line reading ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "expected"),
    [
        ("Human enterovirus C strain CV-A13/USA/1998 VP1 gene", "CVA13"),
        ("Coxsackievirus CVA24 isolate", "CVA24"),
        ("Enterovirus C strain CA13-1998, partial cds", "CVA13"),
        ("Human enterovirus B strain CB3/x", "CVB3"),
        ("Human enterovirus C isolate EV-C99/PAK", "EV-C99"),
        ("Human enterovirus C EVC113 VP1", "EV-C113"),
        ("Human enterovirus A strain EV-A71", "EV-A71"),
        ("Human enterovirus C coxsackievirus a13 strain x", "CVA13"),
    ],
)
def test_the_definition_line_reads_the_abbreviated_forms(definition: str, expected: str) -> None:
    assert type_from_definition(definition) == expected


def test_a_zero_padded_number_is_not_a_type_number() -> None:
    """The seven `FJ4898xx` records: `USA-CA08-10869` is California 2008.

    `CA(\\d{1,2})` has no anchoring word, so it matches. No type in this vocabulary is written
    zero-padded, so the padding is the signal — and the search continues past the token rather than
    stopping, which is what leaves these records where 2.4.1 leaves them.
    """
    definition = "Human enterovirus B strain USA-CA08-10869 viral protein 1 (VP1) gene, partial cds"
    assert type_from_definition(definition) == ""
    # The same shape without the padding is a real type, so the guard is narrow.
    assert type_from_definition(definition.replace("CA08", "CA8")) == "CVA8"


def test_the_token_boundary_keeps_parechovirus_out_of_the_echoviruses() -> None:
    """The upstream defect this port inherits the fix for: 153 records mistyped as echoviruses.

    `echovirus\\s*(\\d+)` with no left boundary matches inside `parechovirus`, and via the carve's
    own membership clause that is also how those records got into an Enterovirus release.
    """
    assert type_from_definition("Human parechovirus 3 strain x") == ""
    assert type_from_definition("Human echovirus 3 strain x") == "E3"


def test_the_definition_line_is_read_only_when_the_name_says_nothing() -> None:
    """A name that states a type is the answer; a title mentioning another one does not override it.

    Deposits routinely name a comparator or a recombination partner in their own title, so reading
    the definition first would let a mentioned type overwrite a stated one.
    """
    outcome = typed(
        organism="Coxsackievirus A24", definition="recombinant with CV-A13 in the 3D region"
    )
    assert outcome.value == "CVA24"
    assert outcome.evidence_basis == BASIS_TYPE_NAME


def test_a_definition_derived_type_says_so_in_its_own_basis() -> None:
    outcome = typed(organism="Enterovirus C", definition="strain CV-A13/USA/1998")
    assert outcome.value == "CVA13"
    assert outcome.evidence_basis == BASIS_TYPE_DEFINITION
    assert outcome.source_field == "definition"


def test_a_record_neither_field_types_reports_the_organism_name_as_the_problem() -> None:
    """The queue groups by what a curator would fix, which is the name and not the title."""
    outcome = typed(organism="Enterovirus C", definition="poliovirus VP1 gene, partial cds")
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_NO_TYPE_IN_NAME
    assert outcome.source_field == "organism_name"
    assert outcome.source_value == "Enterovirus C"


# --- the ledger ---------------------------------------------------------------------------------


def test_a_bare_serotype_digit_from_the_ledger_becomes_a_canonical_type() -> None:
    """`serotype` holds `1`/`2`/`3`, not `PV1`, so it is normalized rather than written through."""
    outcome = typed(organism="Enterovirus C", serotype="2")
    assert outcome.value == "PV2"
    assert outcome.evidence_basis == BASIS_LEDGER
    assert outcome.manual_override is True


def test_an_organism_style_correction_from_the_ledger_goes_through_the_same_parser() -> None:
    assert typed(organism="Enterovirus C", corrected_type="Coxsackievirus A18").value == "CVA18"


def test_the_ledger_fields_rank_most_specific_first() -> None:
    outcome = typed(
        organism="Enterovirus C", corrected_type="Coxsackievirus A18", confirmed_serotype="2",
        serotype="3",
    )
    assert outcome.value == "CVA18"


def test_a_curated_unknown_is_a_decline_and_not_a_fallback_to_the_name() -> None:
    """It records that the type is undetermined, which is what an unresolved cell means. Falling
    back to the name would overturn the curator with the weaker signal."""
    outcome = typed(organism="Coxsackievirus A24", serotype="unknown")
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_CURATED_UNKNOWN
    assert outcome.manual_override is True


def test_a_ledger_non_answer_declines_rather_than_shipping_itself() -> None:
    """`corrected_type` also holds `non-polio enterovirus`, which is not a type."""
    outcome = typed(organism="Enterovirus C", corrected_type="non-polio enterovirus")
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_CURATED_UNKNOWN


def test_a_poliovirus_serotype_from_the_name_reports_its_own_basis() -> None:
    assert typed(organism="Poliovirus 1").evidence_basis == BASIS_SEROTYPE_NAME


# --- the corpus ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def type_provenance(repository_root: Path) -> list[dict[str, str]]:
    return [
        row
        for row in read_projection_provenance(repository_root / "final")
        if row["canonical_field"] == "virus_type"
    ]


def test_the_shipped_release_types_the_declared_populations(
    type_provenance: list[dict[str, str]],
) -> None:
    bases = Counter(
        row["evidence_basis"] for row in type_provenance if not row["unresolved_reason"]
    )
    assert bases[BASIS_TYPE_DEFINITION] == RECOVERED_FROM_DEFINITION
    assert sum(1 for row in type_provenance if row["unresolved_reason"]) == DECLINED_ROWS


def test_no_definition_derived_type_is_zero_padded(
    type_provenance: list[dict[str, str]],
) -> None:
    """The corpus form of the guard: a padded value would be a vocabulary token nothing declares."""
    padded = [
        row["final_value"]
        for row in type_provenance
        if row["evidence_basis"] == BASIS_TYPE_DEFINITION
        and re.search(r"0\d", row["final_value"])
    ]
    assert not padded
