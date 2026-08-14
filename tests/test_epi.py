"""`R-SPECIMEN-2` and `R-SURVEILLANCE-2`: the keyword families, and the flag that never fired.

Both rules had their thresholds and patterns declared and their *behaviour* asserted nowhere. This
covers the two 2026-08-12 changes and the properties they must not break.

The flag branch is the one worth reading twice. `/environmental_sample` is a valueless GenBank
qualifier — all 278 occurrences in this corpus store the empty string — and the rule tested its
value, so the branch had never resolved a single record in any release. Fixing it to test presence
is half the change; the other half is *where* it sits. Above the specimen text it relabels 36
records that name their own specimen, 31 of them stool. Below it, guarded, it resolves 17 and moves
none of the 36.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from enterovirus_genbank_curated.derive.epi import (
    BASIS_ENVIRONMENTAL_FLAG,
    BASIS_GENBANK_DIVISION,
    BASIS_HOST_SPECIES,
    BASIS_SPECIMEN_CONTEXT,
    UNRESOLVED_AMBIGUOUS,
    UNRESOLVED_NO_KEYWORD,
    UNRESOLVED_NO_ORIGIN_EVIDENCE,
    UNRESOLVED_NO_SOURCE,
    UNRESOLVED_NO_STREAM_EVIDENCE,
    sample_origin,
    specimen_type,
    surveillance_stream,
)
from enterovirus_genbank_curated.derive.outcome import RecordView
from enterovirus_genbank_curated.export.metadata import read_projection_provenance

SPECIMEN_PARAMETERS = {
    "patterns": {
        "environmental": (
            r"sewage|wastewater|waste water|effluent|water\b|environmental|treatment plant"
            r"|tretment plant|trunk line|\benvironment\b"
        ),
        "stool": r"stool|faeces|faecal|feces|fecal|rectal",
        "respiratory": r"throat|nasal|nasopharyn|oropharyn|respiratory|sputum|pharyn",
        "CNS": r"\bcsf\b|cerebrospinal|central nervous system|\bcns\b|\bbrain\b",
        "serum": r"serum|blood\b|plasma",
    }
}

STREAM_PARAMETERS = {
    "streams": {
        "environmental": "environmental",
        "healthy_community": "healthy/community",
        "afp_clinical": "AFP/clinical",
        "environmental_pattern": r"sewage|wastewater|waste water|effluent|water\b|environmental",
        "healthy_pattern": r"healthy|close contact|contact of|community",
        "clinical_pattern": (
            r"\bafp\b|acute flaccid|paralysis|paralytic|patient|case of|meningitis|gastroenteritis"
        ),
    },
    "outside_scope_value": "not_applicable",
    "individual_specimen_pattern": (
        r"stool|faeces|faecal|feces|fecal|rectal|throat|nasal|nasopharyn|oropharyn|sputum|pharyn"
        r"|\bcsf\b|cerebrospinal|serum|blood\b|plasma"
    ),
}

ORIGIN_PARAMETERS = {
    "human_host_pattern": r"homo sapiens|\bhuman\b",
    "human_specimen_pattern": (
        r"stool|faeces|faecal|feces|fecal|sewage|wastewater|waste water|water\b|throat|nasal"
        r"|nasopharyn|oropharyn|\bcsf\b|cerebrospinal|serum|blood\b|patient|\bafp\b|acute flaccid"
        r"|paralysis|paralytic|meningitis|gastroenteritis"
    ),
    "origins": {"human": "human", "non_human": "non-human"},
    "outside_scope_value": "unknown",
    "origin_by_division": {"ENV": "human", "PAT": "non-human"},
}

RECOVERED_BY_THE_FLAG = 17
RECOVERED_SPECIMEN_KEYWORDS = 80
RESOLVED_BY_THE_DIVISION = 571


def view(
    source: str = "",
    *,
    environmental_flag: bool = False,
    poliovirus: bool = True,
    division: str = "VRL",
    host: str = "",
    decisions: dict[str, str] | None = None,
) -> RecordView:
    qualifiers = {"isolation_source": source} if source else {}
    if environmental_flag:
        # A valueless qualifier is present with an empty value, which is the whole point.
        qualifiers["environmental_sample"] = ""
    if host:
        qualifiers["host"] = host
    return RecordView(
        version="X00001.1",
        accession="X00001",
        record={"organism_name": "Poliovirus 1", "division": division},
        qualifiers=qualifiers,
        decisions=decisions or {"is_poliovirus": "TRUE" if poliovirus else "FALSE"},
    )


# --- R-SPECIMEN-2, and the keyword families added on 2026-08-12 ----------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("Rahat Treatment Plant", "environmental"),
        ("Be'er Sheva Treatment Plant", "environmental"),
        # One deposit in the series spells it this way, and it is 2 records.
        ("Horashim Tretment Plant", "environmental"),
        ("Ayalon Lod Trunk Line", "environmental"),
        ("Kasefia Trunk line", "environmental"),
        ("environment", "environmental"),
        ("central nervous system; brain", "CNS"),
        # The families that were already there, so the additions did not displace them.
        ("sewage", "environmental"),
        ("stool", "stool"),
        ("throat swab", "respiratory"),
        ("CSF", "CNS"),
        ("serum", "serum"),
    ],
)
def test_the_specimen_keyword_families(source: str, expected: str) -> None:
    outcome = specimen_type(SPECIMEN_PARAMETERS, view(source))
    assert outcome.value == expected


def test_an_epidemiological_frame_is_not_a_specimen() -> None:
    """The `default_stool` line, held. 2.4.1 calls all of these `stool`; none of them names one.

    5,544 further records deposit no `/isolation_source` at all and 2.4.1 calls them `stool` too.
    Adding a pattern for any of this would be reinstating the assumption the rewrite removed.
    """
    for frame in ("AFP case", "paralytic polio case", "healthy individual", "whole cell lysate"):
        outcome = specimen_type(SPECIMEN_PARAMETERS, view(frame))
        assert outcome.value == "", frame
        assert outcome.unresolved_reason == UNRESOLVED_NO_KEYWORD


def test_two_specimens_named_is_still_two_specimens() -> None:
    """The additions must not turn an ambiguous qualifier into a decided one."""
    outcome = specimen_type(
        SPECIMEN_PARAMETERS,
        view("throat swab and stool samples from an immunodeficient individual"),
    )
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_AMBIGUOUS


def test_no_isolation_source_has_its_own_reason() -> None:
    """Distinct from "no keyword": no pattern change can ever resolve it."""
    assert specimen_type(SPECIMEN_PARAMETERS, view()).unresolved_reason == UNRESOLVED_NO_SOURCE


# --- R-SURVEILLANCE-2's environmental flag ------------------------------------------------------


def test_the_flag_is_valueless_and_presence_is_the_signal() -> None:
    """The defect: the branch tested `.strip()` on a qualifier that is always the empty string.

    It had therefore never fired in any release, while its rule description claimed it as the first
    thing read.
    """
    outcome = surveillance_stream(STREAM_PARAMETERS, view("Rahat Treatment Plant",
                                                          environmental_flag=True))
    assert outcome.value == "environmental"
    assert outcome.evidence_basis == BASIS_ENVIRONMENTAL_FLAG
    assert outcome.source_field == "environmental_sample"


def test_the_flag_does_not_overrule_an_individuals_specimen() -> None:
    """31 flagged records name stool, 2 a nasopharyngeal swab. All 33 are non-poliovirus.

    The flag is a statement about the sampling programme; `/isolation_source` is a statement about
    this material. Read the flag first and all 33 become `environmental`, disagreeing with 2.4.1 and
    with the record itself. Read it last and guarded, they keep the determined `not_applicable`
    their partition gives them.
    """
    outcome = surveillance_stream(
        STREAM_PARAMETERS, view("stool", environmental_flag=True, poliovirus=False)
    )
    assert outcome.value == "not_applicable"
    outcome = surveillance_stream(
        STREAM_PARAMETERS, view("nasopharyngeal swab", environmental_flag=True, poliovirus=False)
    )
    assert outcome.value == "not_applicable"


def test_a_flagged_healthy_contact_keeps_its_own_context() -> None:
    """Three records: flagged, and `/isolation_source` naming a healthy contact's stool."""
    outcome = surveillance_stream(
        STREAM_PARAMETERS, view("stool from healthy contact", environmental_flag=True)
    )
    assert outcome.value == "healthy/community"
    assert outcome.evidence_basis == BASIS_SPECIMEN_CONTEXT


def test_an_unflagged_record_naming_no_context_still_declines() -> None:
    """The flag fix must not become a default. No flag, no text, no answer."""
    outcome = surveillance_stream(STREAM_PARAMETERS, view("cell culture"))
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_NO_STREAM_EVIDENCE


def test_the_flag_resolves_a_record_with_no_isolation_source_at_all() -> None:
    """Nothing to contradict it, so the deposit's own declaration stands."""
    outcome = surveillance_stream(STREAM_PARAMETERS, view(environmental_flag=True))
    assert outcome.value == "environmental"
    assert outcome.evidence_basis == BASIS_ENVIRONMENTAL_FLAG


def test_the_flag_is_read_below_the_text_and_not_above_it() -> None:
    """A flagged sewage record resolves through its text, so the basis names the text."""
    outcome = surveillance_stream(STREAM_PARAMETERS, view("sewage", environmental_flag=True))
    assert outcome.value == "environmental"
    assert outcome.evidence_basis == BASIS_SPECIMEN_CONTEXT


# --- R-ORIGIN-2's ENV division branch -------------------------------------------------------------


def test_an_environmental_division_record_is_human_origin() -> None:
    """Sewage is human waste from a human population, which is what 2.4.1 ships on all 19.

    `sample_origin` records *who* was sampled and `surveillance_stream` records *which system*
    sampled them, so there is no environmental value in this vocabulary and none is wanted — the
    two-axis split exists so that "from a sewer" and "from a person" are not the same answer.
    """
    outcome = sample_origin(ORIGIN_PARAMETERS, view("Rahat Treatment Plant", division="ENV"))
    assert outcome.value == "human"
    assert outcome.evidence_basis == BASIS_GENBANK_DIVISION
    assert outcome.source_field == "division"


def test_a_deposited_host_still_outranks_the_division() -> None:
    """The division is a structural fallback, not a rule about who was sampled."""
    outcome = sample_origin(
        ORIGIN_PARAMETERS, view("river water", division="ENV", host="Sus scrofa")
    )
    assert outcome.value == "non-human"
    assert outcome.evidence_basis == BASIS_HOST_SPECIES


@pytest.mark.parametrize(
    ("division", "expected"), [("ENV", "human"), ("PAT", "non-human")]
)
def test_the_division_branch_reaches_non_poliovirus_records_too(
    division: str, expected: str
) -> None:
    """416 records move off the release's `unknown` this way, and that is the intended behaviour.

    21 are non-poliovirus sewage isolates already streamed `environmental`; 377 are non-poliovirus
    patent deposits. 2.4.1 left all of them `unknown` because its `origin_class` was curated for
    poliovirus only — a fact about the upstream process rather than about the record. That is the
    same 2026-07-30 curator decision this rule already applies to `/host`, which is why the branch
    sits above the partition scope rather than below it.
    """
    outcome = sample_origin(
        ORIGIN_PARAMETERS, view("cell culture", division=division, poliovirus=False)
    )
    assert outcome.value == expected
    assert outcome.evidence_basis == BASIS_GENBANK_DIVISION


def test_a_patent_deposit_is_not_a_sample_taken_from_an_organism() -> None:
    """82 records were declining this and 2.4.1 fills 56 of them with `non-human`.

    The other 26 it calls `unknown`, which is a placeholder rather than a determination — the same
    inheritance the `default_stool` and `not_applicable` reviews refused. Curator ruling 2026-08-13.
    """
    outcome = sample_origin(ORIGIN_PARAMETERS, view("", division="PAT"))
    assert outcome.value == "non-human"
    assert outcome.evidence_basis == BASIS_GENBANK_DIVISION


def test_a_division_that_states_nothing_about_origin_is_not_read() -> None:
    """`VRL` is the division of 24,410 of these records and says only "this is a virus"."""
    outcome = sample_origin(ORIGIN_PARAMETERS, view("cell culture", division="VRL"))
    assert outcome.value == ""
    assert outcome.unresolved_reason == UNRESOLVED_NO_ORIGIN_EVIDENCE


def test_the_declared_mapping_is_the_whole_branch() -> None:
    """A division not in the mapping falls through, so adding one is a catalog edit and not a code
    edit. `SYN` is the case that makes this worth pinning: a synthetic-construct deposit is arguably
    non-human too, but R-CONSTRUCT-2 already owns that determination and no measurement asked this
    rule for it."""
    assert set(ORIGIN_PARAMETERS["origin_by_division"]) == {"ENV", "PAT"}
    outcome = sample_origin(ORIGIN_PARAMETERS, view("", division="SYN"))
    assert outcome.value == ""


# --- the corpus ---------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def provenance(repository_root: Path) -> list[dict[str, str]]:
    return read_projection_provenance(repository_root / "final")


def test_the_division_branch_resolves_the_declared_population(
    provenance: list[dict[str, str]],
) -> None:
    bases = Counter(
        row["evidence_basis"]
        for row in provenance
        if row["canonical_field"] == "sample_origin" and not row["unresolved_reason"]
    )
    assert bases[BASIS_GENBANK_DIVISION] == RESOLVED_BY_THE_DIVISION


def test_the_flag_resolves_the_declared_population(provenance: list[dict[str, str]]) -> None:
    bases = Counter(
        row["evidence_basis"]
        for row in provenance
        if row["canonical_field"] == "surveillance_stream" and not row["unresolved_reason"]
    )
    assert bases[BASIS_ENVIRONMENTAL_FLAG] == RECOVERED_BY_THE_FLAG


def test_the_specimen_rule_resolves_what_the_keyword_families_added(
    provenance: list[dict[str, str]],
) -> None:
    """Pinned as a total rather than per keyword: `matching_specimen_types` reports the category it
    resolved to and not which alternative in the pattern matched, so the corpus cannot attribute
    further than this. The per-keyword claims are the unit cases above."""
    resolved = sum(
        1
        for row in provenance
        if row["canonical_field"] == "specimen_type" and not row["unresolved_reason"]
    )
    assert resolved == 11608 + RECOVERED_SPECIMEN_KEYWORDS
