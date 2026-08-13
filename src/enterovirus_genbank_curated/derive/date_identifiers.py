"""A collection year read out of a poliovirus surveillance identifier.

GPEI-era poliovirus isolates are named, not dated: `NIE-KGS-KAN-15-036`, `1234PAK08`, `RUS01-E12`.
The year is in the name, and 1,761 records in this corpus carry one while depositing no
`/collection_date` at all. Until 2026-08-12 every one of those shipped `collection_date_precision =
NA` and a blank date, and `docs/reproducibility.md` blamed an archival reconstruction whose inputs
are not in this repository.

**That premise was wrong, and measuring it is what showed it.** Of the 1,761, 1,690 came from
identifier parsing over fields this repository already carries and 71 from an explicit four-digit
year written into a strain designation. **Zero** came from the archival reconstruction. The whole
population is reachable from `raw/`, and this module reaches it: run over the corpus, it reproduces
the year 2.4.1 shipped on **1,761 of 1,761** records, with no record gaining a year 2.4.1 did not
have and none disagreeing on the value.

## What is declared and what is not

The naming conventions themselves — twenty-one regexes and a set of seventy-two country codes — are
structural, in the same sense as `derive/scope.py`'s label patterns: they encode what a GPEI EPID
number *looks like*, and there is nothing to tune. They live here.

The three numbers that are tunable are declared in `registry/rules.json` and threaded in, because
each one decides whether a year is emitted at all:

* `minimum_inferred_year` / `maximum_inferred_year` — the plausibility window. Load-bearing in both
  directions and measured: without the ceiling `AJ783720/733/804/852` are dated **2028** from the
  isolate `OF2 05/28`, where `05/28` is a specimen number; without the floor `AY948201` is dated
  **1025** from the isolate `CHN1025` and `AB206718` **2083**. A fabricated date is worse than an
  absent one, so an out-of-window year means the convention did not match and the cascade keeps
  looking, rather than the record being abandoned.
* `two_digit_year_pivot` — where `YY` splits between the 1900s and the 2000s. Also load-bearing:
  moving it changes which two-digit tokens survive the window.

## The suppressor

`six_digit_date_or_lab_year` reads the last two digits of *any* six-digit token as a year, which
fabricates dates from patent numbers, lab accessions and NCBI taxon ids. The upstream stage kept the
branch and threw its answer away, and that is not the same as deleting it: because the branch sits
above the loosest rules, a record it matches is one whose identifier text is dominated by numeric
tokens, and removing it lets a later rule read a year out of something else. Measured — deleting it
dates `AB205395` to 2002 from `strain=Cambodia-02`, a record 2.4.1 leaves undated. So it is ported
as what it actually is: a branch that fires and suppresses, named `SUPPRESSED_CONVENTION`.

(`Cambodia-02` plausibly *is* a 2002 isolate. Recovering it is a curator decision about one record,
not a licence to widen a rule that reads years out of taxon ids.)

## Conventions this corpus never exercises

Five of the twenty-one fire on zero records here: `gpei_slash_country_year`,
`pakistan_slash_region_year`, `lab_country_admin_year`, `albania_1996_strain_number` and
`country_year`. They are ported anyway and unit-tested individually, because precedence *is* the
semantics — dropping a branch does not leave its records undated, it lets a looser branch below
read a different year out of the same token. `tests/test_date_identifiers.py` pins the per-branch
corpus counts, so a raw refresh that starts exercising one of them shows up as a moved number
rather than as silence.

Location is not carried. The upstream function also inferred a country, an admin1 and an admin2
from these tokens and no consumer ever read them; `country` and `admin1` come from R-GEO-1 over
`/geo_loc_name`. So `COUNTRY_CODES` here is a membership test and nothing else, which also retires
the upstream table's `SAA`/`SOA` Saudi-Arabia-vs-South-Africa defect rather than porting it.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from enterovirus_genbank_curated.derive.outcome import RecordView

STRAIN_QUALIFIER = "strain"
ISOLATE_QUALIFIER = "isolate"
GEO_QUALIFIER = "geo_loc_name"
COUNTRY_QUALIFIER = "country"
DEFINITION_FIELD = "definition"

# The label a matched convention reports, when the answer is that no year may be read.
SUPPRESSED_CONVENTION = "six_digit_date_or_lab_year"

# Three-letter GPEI country codes, membership only. Sorted, so an addition is a one-line diff.
COUNTRY_CODES = frozenset(
    {
        "AFG", "ALB", "ANG", "ARG", "AZB", "BAN", "BEN", "BFA", "BRA", "BUL",
        "CAE", "CAF", "CAM", "CAV", "CHA", "CHE", "CHN", "CIV", "COL", "DOR",
        "DRC", "ECU", "EGY", "ETH", "GEO", "GHA", "GRE", "GUI", "GUT", "GUY",
        "HAI", "IND", "ING", "IRA", "IRQ", "ISR", "JOR", "KUW", "MAU", "MEX",
        "MMR", "MOL", "NAM", "NEP", "NIC", "NIE", "NIG", "OMA", "PAK", "PAL",
        "PER", "PHL", "POR", "RDC", "RUS", "SAA", "SIL", "SOA", "SOM", "SUD",
        "SYR", "TAJ", "TKM", "TOG", "TUR", "UAE", "UGA", "UKR", "USA", "UZB",
        "VEN", "VTN",
    }
)

# Every four-digit year an identifier could be read as, before the declared window narrows it.
EXPLICIT_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")


def identifier_text(view: RecordView) -> str:
    """The upstream stage's own text blob, uppercased and whitespace-collapsed.

    Strain and isolate lead because the conventions live there; the definition line and the rest of
    the `source` qualifiers follow because some deposits put the EPID number in a `/note` or leave
    it only in the definition. Dropping the qualifiers costs five records and gains one wrong.
    """
    parts = (
        view.qualifier(STRAIN_QUALIFIER),
        view.qualifier(ISOLATE_QUALIFIER),
        view.record.get(DEFINITION_FIELD, ""),
        " ".join(value for value in view.qualifiers.values() if value),
    )
    return re.sub(r"\s+", " ", " | ".join(part for part in parts if part)).upper()


def _geography(view: RecordView) -> str:
    return view.qualifier(GEO_QUALIFIER) or view.qualifier(COUNTRY_QUALIFIER)


# One convention: its label, the pattern, a guard over `(match, text, geography)`, and how it reads
# a year out of the match. Order is precedence and precedence is semantics — the first convention
# whose year survives the declared window wins, and a convention whose year does not survive is
# treated as not having matched, so the cascade continues past it.
Guard = Callable[[re.Match[str], str, str], bool]
Reader = Callable[[re.Match[str], int], int]


def _in_codes(group: int) -> Guard:
    return lambda match, _text, _geo: match.group(group) in COUNTRY_CODES


def _always(_match: re.Match[str], _text: str, _geo: str) -> bool:
    return True


def _needs_geography(_match: re.Match[str], _text: str, geography: str) -> bool:
    return bool(geography)


def _not_in_codes(match: re.Match[str], _text: str, _geo: str) -> bool:
    return match.group(1) not in COUNTRY_CODES


def _mentions(token: str) -> Guard:
    return lambda _match, text, _geo: token in text


def _two_digit(group: int) -> Reader:
    return lambda match, pivot: _pivot(match.group(group), pivot)


def _four_digit(group: int) -> Reader:
    return lambda match, _pivot: int(match.group(group))


def _either(group: int) -> Reader:
    """Four digits are the year; two are a `YY` the pivot has to place."""

    def read(match: re.Match[str], pivot: int) -> int:
        digits = match.group(group)
        return int(digits) if len(digits) == 4 else _pivot(digits, pivot)

    return read


def _fixed(year: int) -> Reader:
    return lambda _match, _pivot: year


def _pivot(digits: str, pivot: int) -> int:
    value = int(digits)
    return 1900 + value if value >= pivot else 2000 + value


CONVENTIONS: tuple[tuple[str, re.Pattern[str], Guard, Reader], ...] = (
    ("gpei_slash_country_year",
     re.compile(r"\b(AFG)/(\d{2})/\d{2}/\d{3,5}_?([A-Z][A-Z]+)?"), _always, _two_digit(2)),
    ("pakistan_slash_region_year",
     re.compile(r"\b([A-Z]{1,3})/\d{1,3}/(\d{2})/\d{3,5}_?([A-Z][A-Z]+)?(?:[^A-Z0-9]*C\d)?"),
     _not_in_codes, _two_digit(2)),
    ("india_state_admin2_year_case",
     re.compile(r"\b(IND)([A-Z]{2})([A-Z]{3})(\d{2})\d+\b"), _always, _two_digit(4)),
    ("gpei_epid_admin_year_case",
     re.compile(r"\b(RDC|DRC)-([A-Z]{2,4})-([A-Z]{2,4})-(\d{2})-\d+\b"), _always, _two_digit(4)),
    ("country_admin_slash_year",
     re.compile(r"\b([A-Z]{3})-([A-Z][A-Z0-9]+)[/-](\d{2})(?:-\d+)?\b"), _in_codes(1),
     _two_digit(3)),
    ("gpei_epid_country_admin_year_case",
     re.compile(r"\bH?([A-Z]{3})-[A-Z]{2,4}-[A-Z]{2,4}-(\d{2})-\d+[A-Z]?\b"), _in_codes(1),
     _two_digit(2)),
    ("country_lab_slash_year_with_exact_text_date",
     re.compile(r"\b([A-Z]{3})\s+\d+/(\d{2})\s+([A-Z][A-Z]+)\s+\d{1,2}\.\d{1,2}\.(\d{4})\b"),
     _in_codes(1), _four_digit(4)),
    ("case_country_year",
     re.compile(r"\b(\d{1,5})([A-Z]{3})(\d{2,4})\b"), _in_codes(2), _either(3)),
    ("pmol_year_sample",
     re.compile(r"\b(PMOL)(\d{2})(\d{4})\b"), _always, _two_digit(2)),
    ("lab_country_admin_year",
     re.compile(r"\b\d+/([A-Z]{3})-([A-Z]{2})/(\d{2})\b"), _in_codes(1), _two_digit(3)),
    ("country_lab_slash_year",
     re.compile(r"\b(CAM)\d+/(\d{2})\b"), _always, _two_digit(2)),
    ("country_year_environment_version",
     re.compile(r"\b([A-Z]{3})(\d{2})-E\d+(?:-V\d+)?\b"), _in_codes(1), _two_digit(2)),
    ("country_year_optional_case",
     re.compile(r"\b([A-Z]{3})(\d{2,4})(?:-\d+)?\b"), _in_codes(1), _either(2)),
    ("pv_lab_country_year",
     re.compile(r"\bPV\d+_\d+(?:-[A-Z0-9]+)?_([A-Z]{3})(\d{2})\b"), _in_codes(1), _two_digit(2)),
    (SUPPRESSED_CONVENTION,
     re.compile(r"\b(\d{6})[A-Z]?\b"), _always,
     lambda match, pivot: _pivot(match.group(1)[-2:], pivot)),
    ("india_sewer_paper_context",
     re.compile(r"\b[A-Z]-SW\d+\b"), _always, _fixed(2001)),
    ("albania_1996_strain_number",
     re.compile(r"\bSTRAIN\s+392[0-9]\b|\b392[0-9]\b"), _mentions("ALBANIA"), _fixed(1996)),
    ("country_year_case",
     re.compile(r"\b([A-Z]{3})(\d{2})(\d{3,5})\b"), _in_codes(1), _two_digit(2)),
    ("embedded_country_four_digit_year",
     re.compile(r"\b[A-Z]*([A-Z]{3})(19\d{2}|20\d{2})\b"), _in_codes(1), _four_digit(2)),
    ("geo_loc_slash_or_dash_year",
     re.compile(r"\b[A-Z0-9]+[/-](\d{2})\b"), _needs_geography, _two_digit(1)),
    ("country_year",
     re.compile(r"\b([A-Z]{3})(\d{2})\b"), _in_codes(1), _two_digit(2)),
)

def identifier_year(
    view: RecordView, *, minimum: int, maximum: int, pivot: int
) -> tuple[str, str, str]:
    """`(year, convention, matched token)`, or `("", "", "")` when no convention reads a year.

    A match on `SUPPRESSED_CONVENTION` returns the convention and its token with an empty year: the
    caller learns that a year was refused rather than never sought, and the cascade stops there.
    """
    text = identifier_text(view)
    geography = _geography(view)
    for label, pattern, allowed, read in CONVENTIONS:
        match = pattern.search(text)
        if match is None or not allowed(match, text, geography):
            continue
        year = read(match, pivot)
        if not minimum <= year <= maximum:
            continue
        if label == SUPPRESSED_CONVENTION:
            return "", label, match.group(0)
        return str(year), label, match.group(0)
    return "", "", ""


EXPLICIT_CONVENTION = "explicit_id_year"


def explicit_designation_year(view: RecordView, *, minimum: int, maximum: int) -> str:
    """The one four-digit year written into a strain or isolate designation, if there is just one.

    `P-1867/PV1/Kanagawa/2002` and `Istanbul/K2/1994` state the year outright, and no country-coded
    convention above reads them. Requiring exactly one distinct in-window year is what keeps
    `PV1/Sabin/1954-2001` from being dated: two years is an interval, not a collection date.
    """
    designation = " ".join((view.qualifier(STRAIN_QUALIFIER), view.qualifier(ISOLATE_QUALIFIER)))
    years = {
        found for found in EXPLICIT_YEAR.findall(designation) if minimum <= int(found) <= maximum
    }
    return years.pop() if len(years) == 1 else ""
