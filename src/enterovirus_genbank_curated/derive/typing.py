"""`virus_type` — the enterovirus type, read out of the organism name.

The shipped `R-TYPE-1` projects a curated `enterovirus_type` or `serotype` and records
`name_derived` as the basis for 12,792 of its rows. That basis is the whole method, and it is
recoverable: the NCBI organism name a depositor chose *is* the type, in a naming convention regular
enough to parse.

Measured over the shipped release: of the 223 distinct organism names on `name_derived` rows, **220
map to exactly one type**. The three that do not are `Enterovirus A`, `Enterovirus B` and
`Enterovirus C` — bare species names, which carry no type at all and were typed upstream from the
sequence. So the name determines the type wherever the name states one, and states nothing where it
does not. That is the cleanest split in this whole rewrite.

## The convention, and the four traps in it

| organism name | type |
|---|---|
| `Coxsackievirus A24`, `Human coxsackievirus A21 Coe` | `CVA24`, `CVA21` |
| `Echovirus E11` | `E11` |
| `Enterovirus A71`, `enterovirus D68` | `EV-A71`, `EV-D68` |
| `rhinovirus C40` | `RV-C40` |
| `Poliovirus 1`, `Human poliovirus 2 strain Sabin` | `PV1`, `PV2` |

Case is not meaningful — `Enterovirus D68` and `enterovirus D68` both occur. Everything after the
type number is not part of the type: `Human coxsackievirus A20a` is `CVA20`, `rhinovirus A1B` is
`RV-A1`, `Human coxsackievirus A24v Marseille/2012/1` is `CVA24`.

Four things this must not do, each of them a real name in the corpus:

1. **`Human poliovirus 30/ROU/2008` is PV2, not PV3.** The `30` is an isolate number. So the
   serotype digit is anchored: one character from `123` with no digit after it. Getting this wrong
   would silently mistype records under a rule that looked right.
2. **`Enterovirus 6`, `Enterovirus 19`, `Enterovirus 103` carry no type.** A bare number with no
   species letter is the pre-2016 numbering, and the release leaves all of them blank. The pattern
   requires the species letter, so they do not match.
3. **`Enterovirus J115` and `Simian enterovirus SV46` carry no type in this vocabulary.** `J` is a
   simian species; the human typing scheme runs `A`–`D`. Restricting the species letter to `A`–`D`
   is what excludes them, and the release agrees — blank on all 17 `J115` records.
4. **`Human rhinovirus 1A` is not `RV-A1`.** Digits-then-letter is the old serial numbering, not the
   species-and-number form. The pattern requires letter-then-digits, so it does not match, and again
   the release ships blank.

## The second reading: the depositor's own definition line

The organism name is NCBI's; the definition line is the depositor's, and it is often where the type
actually is. `Human enterovirus C strain CV-A13/USA/1998` has no type in its organism name and
states `CVA13` in its own title. So when the name says nothing, the definition line is read for the
**abbreviated** forms (`CV-A13`, `CA13`, `EV-C99`) that a title uses and an NCBI organism name never
does. That recovers **427** of the cells the release fills and this rule used to decline, at the
type 2.4.1 shipped, with **no** disagreement and **no** record gaining a type 2.4.1 leaves blank.

Three deliberate narrowings, each measured:

1. **The definition line only** — not `/strain` and `/isolate`, which the frozen upstream stage also
   joined in. Over the 2,216 rows this stage runs on, adding them changes nothing, and they are the
   riskier surface: a strain designation is an identifier full of place and year tokens, and the
   collision below came out of one.
2. **A zero-padded number is not a type number.** `USA-CA08-10869` is a California 2008 designation,
   and the bare `CA` form reads it as Coxsackievirus A8 — on 7 records, 6 of which 2.4.1 types
   `CVB1`. No type in this vocabulary is zero-padded (`CVA13`, never `CVA013`), so a padded number
   means the token is not a type and the next pattern is tried. Dropping the bare `CA`/`CB` forms
   instead was measured too: it also removes 125 correct recoveries, so the guard is the right cut
   and not the pattern.
3. **A canonical value is produced in exactly one place.** Each abbreviated pattern rewrites its
   match into the spelled-out organism-name form and hands it to `type_from_name`, so there is no
   second definition of what `CVA13` looks like that could drift from the first.

## Where it declines, and why that is not the release's blank

A name that states no type, whose record text states none either, is a decline and not a blank. The
distinction matters because the release's blanks are two different things: `Enterovirus C` on 685
records really is "the name does not say, and nothing else was consulted", while the release *did*
type 548 other `Enterovirus C` records from their sequence. Sequence typing is a stage this clone
does not have, so the honest output is an unresolved cell with the reason attached, and the record
joins the curation queue grouped by the organism name that failed to decide it. 883 rows stay there
— 568 `Enterovirus C`, 195 `Enterovirus B`, 82 `Human enterovirus` and 38 others — and they are the
population the deferred EV reference-panel pass is for.

Three named consequences of declining rather than guessing:

* `Enterovirus coxsackiepol` — 82 records the release types `PV2`. The name is a chimera label with
  no serotype in it. A rule that read `pol` and emitted `PV2` would be pattern-matching a single
  string, so this declines.
* `synthetic construct`, `unidentified`, `unidentified poliovirus` — the release types a handful of
  these from sequence. The name cannot.
* `Human poliovirus sp.` — the release ships blank here too, and for the same reason the rule
  declines: nothing states which serotype.

## The ledger's typing fields, and their vocabulary

Three fields reach this column, and they do not speak in canonical values. `serotype` and
`confirmed_serotype` hold a bare `1`, `2`, `3` or `unknown`; `corrected_type` holds an
organism-style name (`Coxsackievirus A18`) or the non-answer `non-polio enterovirus`. So a decision
is normalized through the same parser as a deposited name rather than written straight into the
column, and a curator's `unknown` declines — it is a recorded determination that the type is
undetermined, which is exactly what an unresolved cell means.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from enterovirus_genbank_curated.derive.outcome import RecordView, RuleOutcome
from enterovirus_genbank_curated.registry.rules import rule_implementation

ORGANISM_FIELD = "organism_name"
DEFINITION_FIELD = "definition"

LEDGER_CORRECTED_TYPE = "corrected_type"
LEDGER_CONFIRMED_SEROTYPE = "confirmed_serotype"
LEDGER_SEROTYPE = "serotype"
# Most specific first: an explicit correction outranks a confirmation, which outranks the original.
LEDGER_TYPE_FIELDS = (LEDGER_CORRECTED_TYPE, LEDGER_CONFIRMED_SEROTYPE, LEDGER_SEROTYPE)

BASIS_LEDGER = "curated_type"
BASIS_SEROTYPE_NAME = "poliovirus_serotype_in_organism_name"
BASIS_TYPE_NAME = "enterovirus_type_in_organism_name"
BASIS_TYPE_DEFINITION = "enterovirus_type_in_definition_line"

UNRESOLVED_NO_TYPE_IN_NAME = "organism_name_states_no_type"
UNRESOLVED_CURATED_UNKNOWN = "curated_type_is_unknown"

# `(?![0-9])` is load-bearing: `Human poliovirus 30/ROU/2008` is PV2, and the 30 is an isolate.
_SEROTYPE = re.compile(r"\bpoliovirus\s+(?:type\s+)?([123])(?![0-9])")
# Species letter then number, in that order. `A1B` yields A1; `1A` matches nothing.
_COXSACKIE = re.compile(r"\bcoxsackievirus\s+([ab])\s*([0-9]+)")
_ECHO = re.compile(r"\bechovirus\s+e?\s*([0-9]+)")
_ENTERO = re.compile(r"\benterovirus\s+([a-d])\s*([0-9]+)")
_RHINO = re.compile(r"\brhinovirus\s+([a-c])\s*([0-9]+)")


def serotype_from_name(name: str) -> str:
    """`PV1`/`PV2`/`PV3` if the name states a poliovirus serotype, else empty."""
    match = _SEROTYPE.search(name.lower())
    return f"PV{match.group(1)}" if match else ""


def type_from_name(name: str) -> str:
    """The canonical enterovirus type the organism name states, or empty if it states none.

    Ordered most-specific-first so that a name carrying both a genus and a species letter is read as
    the genus form the vocabulary uses — `Coxsackievirus A24` is `CVA24`, never `EV-A24`.
    """
    text = name.lower()
    if serotype := serotype_from_name(text):
        return serotype
    if match := _COXSACKIE.search(text):
        return f"CV{match.group(1).upper()}{match.group(2)}"
    if match := _ECHO.search(text):
        return f"E{match.group(1)}"
    if match := _ENTERO.search(text):
        return f"EV-{match.group(1).upper()}{match.group(2)}"
    if match := _RHINO.search(text):
        return f"RV-{match.group(1).upper()}{match.group(2)}"
    return ""


# The abbreviated forms a definition line uses, each rewritten into the organism-name form
# `type_from_name` already parses. Ported from the frozen upstream stage's own table, with its
# `_TOKEN_START`/`_TOKEN_END` boundaries kept: without the left one, `echovirus\s*(\d+)` matched
# inside `par|echovirus` and typed 153 human parechovirus records as echoviruses.
#
# `CV-A13` and the bare `CA13` are the same claim written two ways, and both occur. The bare forms
# have no anchoring word at all, which is what makes the zero-padding guard below necessary rather
# than merely tidy.
#
# `EV-C` is separated from `EV-A`/`EV-B`/`EV-D` and requires two or three digits, which is the
# upstream table's own asymmetry, kept: the single-digit `EV-C` spelling does not occur, and
# admitting it would let two-character lab codes through.
_TOKEN_START, _TOKEN_END = r"(?<![A-Za-z0-9])", r"(?![A-Za-z0-9])"
DEFINITION_TYPES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(_TOKEN_START + r"CV[-_]?A[-_]?(\d{1,2})" + _TOKEN_END, re.I),
     "Coxsackievirus A{}"),
    (re.compile(_TOKEN_START + r"CV[-_]?B[-_]?(\d{1,2})" + _TOKEN_END, re.I),
     "Coxsackievirus B{}"),
    (re.compile(_TOKEN_START + r"CA(\d{1,2})" + _TOKEN_END), "Coxsackievirus A{}"),
    (re.compile(_TOKEN_START + r"CB(\d{1,2})" + _TOKEN_END), "Coxsackievirus B{}"),
    (re.compile(_TOKEN_START + r"coxsackievirus\s*a[-\s]?(\d{1,2})", re.I), "Coxsackievirus A{}"),
    (re.compile(_TOKEN_START + r"coxsackievirus\s*b[-\s]?(\d{1,2})", re.I), "Coxsackievirus B{}"),
    (re.compile(_TOKEN_START + r"echovirus\s*(\d{1,2})", re.I), "Echovirus E{}"),
    (re.compile(_TOKEN_START + r"EV[-_]?([ABD])[-_]?(\d{1,3})" + _TOKEN_END), "Enterovirus {}{}"),
    (re.compile(_TOKEN_START + r"enterovirus\s*([ABD])[-\s]?(\d{1,3})", re.I),
     "Enterovirus {}{}"),
    (re.compile(_TOKEN_START + r"EV[-_]?C[-_]?(\d{2,3})" + _TOKEN_END), "Enterovirus C{}"),
)


def _is_zero_padded(groups: tuple[str, ...]) -> bool:
    """`CA08` in `USA-CA08-10869` is a California 2008 designation, not Coxsackievirus A8."""
    return any(part.isdigit() and len(part) > 1 and part.startswith("0") for part in groups)


def type_from_definition(text: str) -> str:
    """The type the record's own definition line states in abbreviated form, or empty.

    A zero-padded number means the token is not a type, so the search continues rather than
    stopping: on the seven `FJ4898xx` California records the next pattern matches nothing, which is
    the answer 2.4.1 ships on the one it leaves blank.
    """
    for pattern, organism_form in DEFINITION_TYPES:
        match = pattern.search(text)
        if match is None or _is_zero_padded(match.groups()):
            continue
        return type_from_name(organism_form.format(*match.groups()))
    return ""


def _curated_type(view: RecordView) -> tuple[str, str, str]:
    """The ledger's answer as (field, raw value, canonical type). Canonical is empty if unusable."""
    for field in LEDGER_TYPE_FIELDS:
        asserted = view.decisions.get(field, "")
        if not asserted:
            continue
        if asserted in {"1", "2", "3"}:
            return field, asserted, f"PV{asserted}"
        return field, asserted, type_from_name(asserted)
    return "", "", ""


@rule_implementation(
    "derive.typing.virus_type",
    parameters=(),
    evidence_bases=(
        BASIS_LEDGER,
        BASIS_SEROTYPE_NAME,
        BASIS_TYPE_NAME,
        BASIS_TYPE_DEFINITION,
    ),
)
def virus_type(parameters: Mapping[str, Any], view: RecordView) -> RuleOutcome:
    """A curated type, then the organism name, then the definition line, else decline."""
    del parameters

    field, raw, curated = _curated_type(view)
    if field:
        if not curated:
            return RuleOutcome(
                value="",
                evidence_basis="",
                source_field=field,
                source_value=raw,
                unresolved_reason=UNRESOLVED_CURATED_UNKNOWN,
                manual_override=True,
            )
        return RuleOutcome(
            value=curated,
            evidence_basis=BASIS_LEDGER,
            source_field=field,
            source_value=raw,
            manual_override=True,
        )

    organism = view.record.get(ORGANISM_FIELD, "")
    serotype = serotype_from_name(organism)
    if derived := (serotype or type_from_name(organism)):
        return RuleOutcome(
            value=derived,
            evidence_basis=BASIS_SEROTYPE_NAME if serotype else BASIS_TYPE_NAME,
            source_field=ORGANISM_FIELD,
            source_value=organism,
        )

    definition = view.record.get(DEFINITION_FIELD, "")
    if from_definition := type_from_definition(definition):
        return RuleOutcome(
            value=from_definition,
            evidence_basis=BASIS_TYPE_DEFINITION,
            source_field=DEFINITION_FIELD,
            source_value=definition,
        )

    # The organism name is still what is reported as unresolved, not the definition line: it is the
    # field a curator would fix, and the queue groups by it.
    return RuleOutcome(
        value="",
        evidence_basis="",
        source_field=ORGANISM_FIELD,
        source_value=organism,
        unresolved_reason=UNRESOLVED_NO_TYPE_IN_NAME,
    )
