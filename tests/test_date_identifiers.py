"""`R-DATE-2`'s identifier branch: every convention, the traps, and the corpus counts.

The 1,761 records this recovers were recorded for months as unreachable from `raw/`. They were
reachable all along, and `tests/test_canonical_transitions.py` pins the corpus result (zero
differences from 2.4.1's `collection_date` over all 24,296 shared rows). This file pins the
reasoning, because a cascade whose total is right can still have every branch wrong.

Three things are tested that a total cannot see:

* **Each convention individually**, including the five that fire on zero records in this corpus.
  Those five are ported and tested rather than deleted, because in a precedence cascade removing a
  branch does not leave its records undated — it lets a looser branch below read a different year
  out of the same token. Two of them (`lab_country_admin_year`, `country_year`) are shadowed by a
  broader pattern above and are only reachable when that pattern misses; the tests construct
  exactly that, which is also the explanation for why the corpus count is zero.
* **The plausibility window in both directions**, on the four records that motivated each bound.
* **The per-convention corpus counts**, read from the shipped provenance. A refresh that starts
  exercising a dormant convention, or stops exercising a live one, moves a number here.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.derive.date_identifiers import (
    CONVENTIONS,
    SUPPRESSED_CONVENTION,
    explicit_designation_year,
    identifier_text,
    identifier_year,
)
from enterovirus_genbank_curated.derive.dates import (
    BASIS_IDENTIFIER_YEAR,
    IDENTIFIER_SOURCE_PREFIX,
    collection_date,
    collection_date_precision,
)
from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.export.metadata import read_projection_provenance

WINDOW = {"minimum": 1930, "maximum": 2026}
PIVOT = 50

# The declared parameter values, as `derive/apply.py` hands them over: strings, from the catalog.
PARAMETERS = {
    "output_pattern": "^[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?$",
    "precisions": ["day", "month", "year", "range"],
    "not_applicable": "NA",
    "minimum_inferred_year": "1930",
    "maximum_inferred_year": "2026",
    "two_digit_year_pivot": "50",
}

# What the identifier branch recovered, by convention, over the shipped release. Sums to 1,761.
CORPUS_COUNTS = {
    "case_country_year": 427,
    "geo_loc_slash_or_dash_year": 275,
    "country_year_optional_case": 207,
    "gpei_epid_country_admin_year_case": 205,
    "country_year_case": 189,
    "country_year_environment_version": 139,
    "country_admin_slash_year": 119,
    "explicit_id_year": 71,
    "india_sewer_paper_context": 31,
    "india_state_admin2_year_case": 29,
    "pmol_year_sample": 26,
    "gpei_epid_admin_year_case": 13,
    "embedded_country_four_digit_year": 12,
    "country_lab_slash_year_with_exact_text_date": 11,
    "pv_lab_country_year": 6,
    "country_lab_slash_year": 1,
}
RECOVERED_ROWS = 1761

# Ported, unit-tested here, and matched by nothing in this corpus. Not dead code: see the module
# docstring. `SUPPRESSED_CONVENTION` is absent for a different reason — it fires and refuses.
DORMANT_CONVENTIONS = frozenset(
    {
        "gpei_slash_country_year",
        "pakistan_slash_region_year",
        "lab_country_admin_year",
        "albania_1996_strain_number",
        "country_year",
    }
)


def view(
    *,
    strain: str = "",
    isolate: str = "",
    definition: str = "",
    geography: str = "",
    qualifiers: dict[str, str] | None = None,
    date: str = "",
    decisions: dict[str, str] | None = None,
) -> RecordView:
    held = dict(qualifiers or {})
    for name, value in (
        ("strain", strain),
        ("isolate", isolate),
        ("geo_loc_name", geography),
        ("collection_date", date),
    ):
        if value:
            held[name] = value
    return RecordView(
        version="X00001.1",
        accession="X00001",
        record={"definition": definition, "organism_name": "Poliovirus 1"},
        qualifiers=held,
        decisions=decisions if decisions is not None else {"is_poliovirus": "TRUE"},
    )


def year_of(**kwargs: object) -> tuple[str, str]:
    """`(year, convention)` for one constructed record."""
    found, convention, _token = identifier_year(view(**kwargs), pivot=PIVOT, **WINDOW)  # type: ignore[arg-type]
    return found, convention


# --- the text the conventions read -------------------------------------------------------------


def test_the_text_is_strain_then_isolate_then_definition_then_the_qualifiers() -> None:
    text = identifier_text(
        view(strain="s1", isolate="i2", definition="d3", qualifiers={"note": "n4"})
    )
    assert text.startswith("S1 | I2 | D3 | ")
    assert "N4" in text
    # Whitespace is collapsed before matching, so a wrapped GenBank line cannot break a `\b`.
    assert "  " not in identifier_text(view(definition="a   b"))


def test_the_qualifiers_are_part_of_the_text_and_not_decoration() -> None:
    """Dropping them costs five records and gains one wrong, so their inclusion is load-bearing."""
    assert year_of(qualifiers={"note": "1234PAK08"}) == ("2008", "case_country_year")


# --- each convention, in precedence order -------------------------------------------------------


@pytest.mark.parametrize(
    ("convention", "expected", "kwargs"),
    [
        ("gpei_slash_country_year", "2008", {"isolate": "AFG/08/12/34567"}),
        ("pakistan_slash_region_year", "2009", {"isolate": "SD/12/09/12345"}),
        ("india_state_admin2_year_case", "2008", {"isolate": "INDUPMRD08123"}),
        ("gpei_epid_admin_year_case", "2009", {"isolate": "RDC-KAT-KAL-09-123"}),
        ("country_admin_slash_year", "2015", {"isolate": "NIE-KGS-15-036"}),
        ("gpei_epid_country_admin_year_case", "2015", {"isolate": "NIE-KGS-KAN-15-036"}),
        (
            "country_lab_slash_year_with_exact_text_date",
            "1998",
            {"isolate": "ISR 123/98 TEL 12.03.1998"},
        ),
        ("case_country_year", "2008", {"isolate": "1234PAK08"}),
        ("pmol_year_sample", "2009", {"isolate": "PMOL091234"}),
        ("country_lab_slash_year", "2008", {"isolate": "CAM123/08"}),
        ("country_year_environment_version", "2001", {"isolate": "RUS01-E12"}),
        ("country_year_optional_case", "2008", {"isolate": "PAK08-123"}),
        ("pv_lab_country_year", "2008", {"isolate": "PV1_123_PAK08"}),
        ("india_sewer_paper_context", "2001", {"isolate": "M-SW12"}),
        (
            "albania_1996_strain_number",
            "1996",
            {"definition": "Poliovirus 1 from Albania, isolate 3924"},
        ),
        ("country_year_case", "2008", {"isolate": "PAK08123"}),
        ("embedded_country_four_digit_year", "2008", {"isolate": "XPAK2008"}),
        ("geo_loc_slash_or_dash_year", "1998", {"isolate": "OF2-98", "geography": "South Africa"}),
    ],
)
def test_each_convention_reads_its_own_year(
    convention: str, expected: str, kwargs: dict[str, str]
) -> None:
    assert year_of(**kwargs) == (expected, convention)


def test_every_convention_is_covered_by_a_test_in_this_file() -> None:
    """The check that stops a convention being added with no test, which is how a cascade rots."""
    declared = {label for label, _pattern, _guard, _read in CONVENTIONS}
    exercised = set(CORPUS_COUNTS) | DORMANT_CONVENTIONS | {SUPPRESSED_CONVENTION}
    assert declared == exercised - {"explicit_id_year"}, (
        "a convention exists that neither the corpus counts, the dormant list nor the suppressor "
        "names; add it to whichever is true and give it a branch test above"
    )


# --- the two shadowed conventions, and why their corpus count is zero -----------------------------


def test_a_shadowed_convention_is_reachable_only_when_the_one_above_it_misses() -> None:
    """`lab_country_admin_year` sits under a strictly broader pattern.

    `12/ISR-TA/98` is matched by `country_admin_slash_year` at the same position and with the same
    country-code guard, so that branch always wins — which is the whole reason the corpus count is
    zero rather than any statement about the data. It becomes reachable only when the broader
    pattern's *first* match in the text has a prefix that is not a country code, since a guard
    rejects the one match `re.search` found rather than continuing the scan.
    """
    assert year_of(isolate="12/ISR-TA/98") == ("1998", "country_admin_slash_year")
    assert year_of(isolate="XYZ-AB/99 12/ISR-TA/98") == ("1998", "lab_country_admin_year")


def test_the_bare_country_year_convention_is_shadowed_the_same_way() -> None:
    """`PAK08` alone is read by `country_year_optional_case`; `country_year` is the same match.

    `XYZ123` blocks the broader pattern without blocking the narrower one — three digits satisfy
    its `\\d{2,4}` and fail the other's `\\d{2}` — so this is the shape in which the last convention
    in the cascade can still decide a record.
    """
    assert year_of(isolate="PAK08") == ("2008", "country_year_optional_case")
    assert year_of(isolate="XYZ123 PAK08") == ("2008", "country_year")


def test_precedence_is_not_incidental() -> None:
    """A capsid-style example where two conventions match and the earlier one has to win.

    `CAM123/08` is `country_lab_slash_year` (2008). `country_year_optional_case` also matches it and
    reads `123` as a `YY`, which the pivot maps to 2023 — a wrong year that is inside the window, so
    nothing downstream would catch it. Order is the only thing that does.
    """
    assert year_of(isolate="CAM123/08") == ("2008", "country_lab_slash_year")
    assert year_of(isolate="CAM123") == ("2023", "country_year_optional_case")


def test_a_country_code_that_is_not_one_stops_the_convention() -> None:
    assert year_of(isolate="ZZZ08-123") == ("", "")


def test_the_geography_gated_convention_needs_geography() -> None:
    """Negative control for `geo_loc_slash_or_dash_year`, whose whole guard is the location."""
    assert year_of(isolate="OF2-98", geography="South Africa") == (
        "1998",
        "geo_loc_slash_or_dash_year",
    )
    assert year_of(isolate="OF2-98") == ("", "")


def test_the_albania_convention_needs_the_country_named_in_the_text() -> None:
    assert year_of(definition="Poliovirus 1 isolate 3924") == ("", "")


# --- the plausibility window ---------------------------------------------------------------------


def test_the_ceiling_refuses_a_specimen_number_read_as_a_future_year() -> None:
    """`AJ783720`/`733`/`804`/`852`, isolate `OF2 05/28`, where `05/28` is a specimen number.

    Without the ceiling all four are dated 2028. With it the convention is treated as not having
    matched, the cascade continues, nothing else matches, and the record stays dateless — which is
    what 2.4.1 ships.
    """
    assert year_of(isolate="OF2 05/28", geography="South Africa: Gauteng") == ("", "")
    assert year_of(isolate="OF2 05/26", geography="South Africa: Gauteng") == (
        "2026",
        "geo_loc_slash_or_dash_year",
    )


def test_the_floor_refuses_a_serial_number_read_as_a_mediaeval_year() -> None:
    """`AY948201`, isolate `CHN1025`, dated **1025** before the floor existed."""
    assert year_of(isolate="CHN1025") == ("", "")


def test_an_out_of_window_year_does_not_abandon_the_record() -> None:
    """The window means "that token carries no year", so the cascade keeps looking.

    Bolting the check on after the cascade instead — which is how the upstream stage did it — throws
    the whole record away on a single bad match.
    """
    assert year_of(isolate="CHN1025 1234PAK08") == ("2008", "case_country_year")


# --- the suppressor ------------------------------------------------------------------------------


def test_a_six_digit_token_suppresses_the_cascade_rather_than_dating_the_record() -> None:
    """`AB205395`: `taxon:138950` is six digits, and `strain=Cambodia-02` is below it.

    Deleting the branch dates the record 2002 from the strain name — plausible, and not what 2.4.1
    ships. It is a curator's call on one record, not a licence for a rule that reads years out of
    taxon ids.
    """
    year, convention = year_of(strain="Cambodia-02", qualifiers={"db_xref": "taxon:138950"})
    assert (year, convention) == ("", SUPPRESSED_CONVENTION)
    assert year_of(strain="Cambodia-02", geography="Cambodia") == (
        "2002",
        "geo_loc_slash_or_dash_year",
    )


def test_the_suppressor_does_not_block_the_explicit_designation_pass() -> None:
    """The fourteen `FR7155xx` records, and the bug that lost all of them.

    Their `/isolate` is `30-ROU-2008` and their `db_xref` is `taxon:909391`. The suppressor matches
    the taxon id first, which says nothing about whether the designation spells out a year — and it
    does. An earlier draft returned as soon as the suppressor fired and left all fourteen `NA`.
    """
    record = view(isolate="30-ROU-2008", qualifiers={"db_xref": "taxon:909391"})
    assert identifier_year(record, pivot=PIVOT, **WINDOW)[1] == SUPPRESSED_CONVENTION
    assert explicit_designation_year(record, **WINDOW) == "2008"
    assert collection_date(PARAMETERS, record).value == "2008"


# --- the explicit-designation pass ---------------------------------------------------------------


def test_an_explicit_four_digit_year_in_a_designation_is_read() -> None:
    assert explicit_designation_year(view(strain="P-1867/PV1/Kanagawa/2002"), **WINDOW) == "2002"


def test_two_distinct_years_in_a_designation_are_an_interval_and_not_a_date() -> None:
    assert explicit_designation_year(view(strain="PV1/Sabin/1954-2001"), **WINDOW) == ""


def test_the_same_year_twice_is_still_one_year() -> None:
    assert explicit_designation_year(view(strain="1994/K2/1994"), **WINDOW) == "1994"


def test_the_designation_pass_reads_only_strain_and_isolate() -> None:
    """Deliberately narrower than the cascade: a bare year anywhere in a definition line is
    usually a publication or a patent date, not a collection date."""
    record = view(definition="Poliovirus 1, submitted 2002")
    assert explicit_designation_year(record, **WINDOW) == ""


# --- integration with the date rules -------------------------------------------------------------


def test_a_deposited_date_wins_over_an_identifier() -> None:
    record = view(isolate="1234PAK08", date="1995-03-04")
    assert collection_date(PARAMETERS, record).value == "1995-03-04"
    assert collection_date_precision(PARAMETERS, record).value == "day"


def test_a_curated_year_wins_over_an_identifier() -> None:
    record = view(
        isolate="1234PAK08",
        decisions={"is_poliovirus": "TRUE", "collection_year_curated": "1937"},
    )
    outcome = collection_date(PARAMETERS, record)
    assert outcome.value == "1937"
    assert outcome.manual_override is True


def test_a_non_poliovirus_record_is_not_dated_from_a_surveillance_identifier() -> None:
    """The conventions are GPEI-specific, so the gate is the curated partition.

    `AY843310`/`AY843311`/`EF015011`/`FJ489891` are the reason it is not a formality: they carry
    GPEI-style `OMA98`/`OMA99` names because they came out of a polio surveillance lab, and they are
    EV-B80, EV-C99 and EV-B.
    """
    record = view(isolate="1234PAK08", decisions={"is_poliovirus": "FALSE"})
    assert collection_date(PARAMETERS, record).value == ""
    assert collection_date_precision(PARAMETERS, record).value == "NA"


def test_an_identifier_year_is_never_a_manual_override() -> None:
    """It is a rule reading a naming convention, not a curator having looked at the record."""
    outcome = collection_date(PARAMETERS, view(isolate="1234PAK08"))
    assert outcome.manual_override is False
    assert outcome.evidence_basis == BASIS_IDENTIFIER_YEAR
    assert outcome.source_field == f"{IDENTIFIER_SOURCE_PREFIX}case_country_year"
    assert outcome.source_value == "1234PAK08"


def test_the_precision_rule_agrees_with_the_value_rule() -> None:
    record = view(isolate="1234PAK08")
    assert collection_date(PARAMETERS, record).value == "2008"
    assert collection_date_precision(PARAMETERS, record).value == "year"
    assert collection_date_precision(PARAMETERS, record).evidence_basis == BASIS_IDENTIFIER_YEAR


# --- the corpus ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def identifier_provenance(repository_root: Path) -> list[dict[str, str]]:
    return [
        row
        for row in read_projection_provenance(repository_root / "final")
        if row["canonical_field"] == "collection_date"
        and row["evidence_basis"] == BASIS_IDENTIFIER_YEAR
    ]


def test_the_shipped_release_recovers_the_declared_population(
    identifier_provenance: list[dict[str, str]],
) -> None:
    assert len(identifier_provenance) == RECOVERED_ROWS
    assert all(row["final_value"] for row in identifier_provenance)


def test_each_convention_recovers_the_number_it_declares(
    identifier_provenance: list[dict[str, str]],
) -> None:
    """Per convention, not just the total. A rewrite that keeps 1,761 while moving records between
    conventions has changed which naming convention dated which record, and that is a change."""
    measured = Counter(
        row["source_field"].removeprefix(IDENTIFIER_SOURCE_PREFIX)
        for row in identifier_provenance
    )
    assert dict(measured) == CORPUS_COUNTS
    assert sum(CORPUS_COUNTS.values()) == RECOVERED_ROWS


def test_the_dormant_conventions_are_still_dormant(
    identifier_provenance: list[dict[str, str]],
) -> None:
    """Named zeros. A refresh that starts exercising one of these should surface as a moved number,
    not as a branch quietly beginning to decide records."""
    fired = {
        row["source_field"].removeprefix(IDENTIFIER_SOURCE_PREFIX)
        for row in identifier_provenance
    }
    assert not fired & DORMANT_CONVENTIONS
    assert SUPPRESSED_CONVENTION not in fired
