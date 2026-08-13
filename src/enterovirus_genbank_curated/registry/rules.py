"""The deterministic rule catalog: declared data in `registry/rules.json`, bound to code here.

`registry/schemas/rules.schema.json` has existed since the first PR with **no instance** — a
contract with nothing to validate (backlog B17/B18). Its `rule_id` pattern, its `rule_version`
pattern, its `status` enum and its `additionalProperties: false` were therefore entirely
unexercised, and the shipped `final/audit/rules.tsv.gz` carries only four of the seven required
fields, with every threshold embedded in prose. This module is the instance, and
`evgc validate-contracts` validates it.

## Why JSON and not TSV

`parameters` is an object. A TSV cell holding `{"wild_threshold": "0.15"}` contains double quotes,
so a standard csv writer would wrap and escape the field — the exact artifact
`registry/decisions.tsv` forbids so that `cut -f`, `awk -F'\\t'`, a spreadsheet import and
`pandas.read_csv` all agree.

## Why the catalog is in the shipped order, not sorted by rule_id

Because the order *is* data: `export/audit.py` regenerates `final/audit/rules.tsv.gz` byte-for-byte
from this file, which is a free parity gate on a shipped artifact and the thing that proves the
catalog describes the release rather than merely resembling it. Sorting by `rule_id` would put the
release's order in code instead, on the build side of a boundary where release knowledge does not
belong. The declared order is also the readable one: projection rules first, then thresholds.

## Why thresholds are strings

`"0.15"`, not `0.15`. A JSON float round-trips through `repr` differently across versions, which
would break the byte-stable serialization `canonical_catalog_text` depends on, and a threshold
parsed at the point of use cannot acquire a platform float-drift class in the file itself.

What the readers do with them is not uniform, and this docstring claimed otherwise until
2026-08-12: it said comparisons use `Fraction` or integer cross-multiplication. `Fraction` appears
nowhere in this repository. `derive/classification.py` parses thresholds with `Decimal`,
`derive/evidence.py` with `float` and `int`, and several parameters are not numbers at all —
`derive/epi.py` and `derive/dates.py` read regexes, `derive/partition.py` reads controlled
vocabularies. The one property actually enforced is that every leaf is a `str`
(`scalar_parameters`), which is what `assert_parameters_are_described` needs to match them against
their own prose.

## Why `implementation` is a key and not an import path

The schema calls it "Import path or stable implementation key". It is used strictly as a **key**,
resolved through `RULE_IMPLEMENTATIONS`. A data file whose contents name an importable path is a
data file that executes code, and `registry/` is meant to be hand-editable.

`bind_rules` fails in both directions. An orphan *rule* (a catalog row naming an implementation that
is neither registered nor declared pending) is the obvious error. An orphan *implementation* — code
computing a value no published rule declares — is the one that matters, because that is how a
published rule table and the code it claims to describe drift apart. B18 exists because nothing
compared them.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterovirus_genbank_curated.contracts import (
    CANONICAL_COLUMNS,
    ContractError,
    validate_schema_document,
)

RULES_CATALOG_PATH = "registry/rules.json"
RULES_SCHEMA_TITLE = "Deterministic curation rule"

# Field order inside a catalog record, and the order `canonical_catalog_text` writes. Taken from the
# schema's `required` list, which is checked against this below.
RULE_FIELD_ORDER = (
    "rule_id",
    "rule_version",
    "field_name",
    "description",
    "implementation",
    "parameters",
    "status",
)
ACTIVE_RULE_STATUS = "active"
# Every rule in the catalog: the 28 release 2.4.1 published, plus the 10 the rewrite added. Since
# 2026-08-12 `export/audit.py` publishes all of them, so this is also the shipped `rules.tsv.gz` row
# count — the two were deliberately different numbers while the view was pinned to 2.4.1's subset,
# and that is exactly what left 84.6% of provenance rows citing a rule the release did not carry.
EXPECTED_RULE_COUNT = 38
# `BASELINE_VIEW_RULE_COUNT = 28` stood here until 2026-08-12: how many rules carried 2.4.1's own
# `rule_version` and so appeared in the frozen `final/audit/rules.tsv.gz`. The view is the whole
# catalog now, so the number counts nothing and is gone rather than kept as prose.


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    rule_version: str
    field_name: str
    description: str
    implementation: str
    parameters: Mapping[str, Any]
    status: str

    def as_record(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in RULE_FIELD_ORDER}


@dataclass(frozen=True)
class RuleContract:
    """The catalog contract, derived from the published schema rather than restated here."""

    fields: tuple[str, ...]
    non_blank: frozenset[str]
    patterns: tuple[tuple[str, re.Pattern[str]], ...]
    enums: tuple[tuple[str, frozenset[str]], ...]
    object_fields: frozenset[str]


@dataclass(frozen=True)
class RuleImplementation:
    key: str
    required_parameters: frozenset[str]
    declared_bases: frozenset[str]
    fn: Callable[..., Any]
    # Canonical fields this body emits, when it emits more than the catalog's own `field_name`.
    # R-DATE-RANGE-1 is the case that forced it: one rule, two columns. Empty means single-field.
    fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class BoundRule:
    spec: RuleSpec
    implementation: RuleImplementation | None
    pending_reason: str


RULE_IMPLEMENTATIONS: dict[str, RuleImplementation] = {}

# Every rule whose body does not exist yet, and the input it is waiting on. The same honesty
# `derive/metadata.py`'s `PENDING_COLUMNS` provides for columns, at the rule layer. Two kinds:
# superseded 2.4.1 keys retained so the published catalog still lists the rule its successor
# replaced, and stages genuinely unwritten. 26 entries against 12 registered bodies, which is the
# 38 the catalog declares. (This comment read "28 of 28 today" until 2026-08-12, a count that
# matched neither number.)
PENDING_IMPLEMENTATIONS: dict[str, str] = {
    "derive.scope.sequence_scope": "needs record_type, derived against Sabin VP1 coordinates",
    "derive.typing.virus_type_v241": (
        "superseded by R-TYPE-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.classification.poliovirus_classification_v241": (
        "superseded by R-CLASS-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.classification.reconcile_aa_band": "needs capsid AA p-distance",
    "derive.epi.sample_origin_v241": (
        "superseded by R-ORIGIN-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.epi.surveillance_stream_v241": (
        "superseded by R-SURVEILLANCE-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.epi.specimen_type_v241": (
        "superseded by R-SPECIMEN-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.dates.collection_date_v241": (
        "superseded by R-DATE-2; retained only so the frozen 2.4.1 rule view still lists R-DATE-1"
    ),
    "derive.dates.collection_date_precision_v241": (
        "superseded by R-DATE-PRECISION-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.dates.collection_year_bounds_v241": (
        "superseded by R-DATE-RANGE-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.engineered.engineered_or_construct_v241": (
        "superseded by R-CONSTRUCT-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.carve.canonical_inclusion": (
        "the carve predicate exists in derive/metadata.py but is not yet a bound rule"
    ),
    "derive.geo.locality_v241": (
        "superseded by R-GEO-LOCALITY-2; retained for the frozen 2.4.1 rule view"
    ),
    "derive.evidence.sequence_tier_wild": "needs the pairwise sequence-evidence stage",
    "derive.evidence.sequence_tier_sabin_like": "needs the pairwise sequence-evidence stage",
    "derive.evidence.poliovirus_membership": "needs the pairwise sequence-evidence stage",
    "derive.evidence.serotype_coverage_guard": "needs the pairwise sequence-evidence stage",
    "derive.recombination.scoring_windows": "needs the pairwise sequence-evidence stage",
    "derive.recombination.chimera_tier": "needs the pairwise sequence-evidence stage",
    "derive.recombination.capsid_free_promotion": "needs the pairwise sequence-evidence stage",
    "derive.ev_typing.nt_identity": (
        "needs a per-EV-type reference panel, which no declared input carries"
    ),
    "derive.ev_typing.overlap_floor": "needs a per-EV-type reference panel",
    "derive.ev_typing.polio_suspect_overlap_floor": "needs a per-EV-type reference panel",
    "derive.ev_typing.kmer_prefilter": "needs a per-EV-type reference panel",
    "derive.ev_typing.topk_same_type": "needs a per-EV-type reference panel",
    "derive.ev_typing.topk_all": "needs a per-EV-type reference panel",
}


def rule_implementation(
    key: str,
    *,
    parameters: Iterable[str],
    evidence_bases: Iterable[str],
    fields: Iterable[str] = (),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a rule body under a stable key. Duplicate keys fail at import.

    `fields` is for a rule projecting more than one canonical column. Such a body returns a mapping
    of field to outcome rather than a single outcome, and `derive/apply.py` requires the keys to
    equal the declared set, so a rule cannot quietly start writing an undeclared column.
    """

    def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
        if key in RULE_IMPLEMENTATIONS:
            raise ContractError(f"duplicate rule implementation key: {key}")
        RULE_IMPLEMENTATIONS[key] = RuleImplementation(
            key=key,
            required_parameters=frozenset(parameters),
            declared_bases=frozenset(evidence_bases),
            fn=fn,
            fields=tuple(fields),
        )
        return fn

    return decorate


def load_rule_contract(schema_path: Path) -> RuleContract:
    schema = validate_schema_document(schema_path, required_title=RULES_SCHEMA_TITLE)
    properties: dict[str, Any] = schema["properties"]
    fields = tuple(schema["required"])
    if fields != RULE_FIELD_ORDER:
        raise ContractError(
            f"{schema_path}: required properties must match the declared field order; schema "
            f"declares {list(fields)}"
        )
    if set(properties) < set(fields):
        raise ContractError(f"{schema_path}: required names a property that is not declared")

    non_blank: set[str] = set()
    patterns: list[tuple[str, re.Pattern[str]]] = []
    enums: list[tuple[str, frozenset[str]]] = []
    object_fields: set[str] = set()
    for name in fields:
        spec = properties[name]
        if not isinstance(spec, dict):
            raise ContractError(f"{schema_path}: property {name!r} must be an object")
        declared = spec.get("type")
        if declared == "object":
            object_fields.add(name)
        elif declared != "string":
            raise ContractError(f"{schema_path}: property {name!r} must be a string or an object")
        if int(spec.get("minLength", 0)) >= 1:
            non_blank.add(name)
        pattern = spec.get("pattern")
        if pattern is not None:
            try:
                patterns.append((name, re.compile(pattern)))
            except re.error as exc:
                raise ContractError(f"{schema_path}: {name} pattern is invalid: {exc}") from exc
        allowed = spec.get("enum")
        if allowed is not None:
            if not isinstance(allowed, list) or not allowed:
                raise ContractError(f"{schema_path}: {name} enum must be a non-empty list")
            enums.append((name, frozenset(allowed)))

    status_enum = dict(enums).get("status")
    if status_enum is None or ACTIVE_RULE_STATUS not in status_enum:
        raise ContractError(f"{schema_path}: status must enumerate {ACTIVE_RULE_STATUS!r}")
    return RuleContract(
        fields=fields,
        non_blank=frozenset(non_blank),
        patterns=tuple(patterns),
        enums=tuple(enums),
        object_fields=frozenset(object_fields),
    )


def _validate_record(record: Any, contract: RuleContract, where: str) -> RuleSpec:
    if not isinstance(record, dict):
        raise ContractError(f"{where}: each catalog entry must be an object")
    actual, expected = set(record), set(contract.fields)
    missing, undeclared = sorted(expected - actual), sorted(actual - expected)
    if missing or undeclared:
        raise ContractError(f"{where}: missing fields {missing}, undeclared fields {undeclared}")
    for name in contract.object_fields:
        if not isinstance(record[name], dict):
            raise ContractError(f"{where}: {name} must be an object")
    for name in contract.fields:
        if name in contract.object_fields:
            continue
        if not isinstance(record[name], str):
            raise ContractError(f"{where}: {name} must be a string")
    for name, pattern in contract.patterns:
        if not pattern.fullmatch(record[name]):
            raise ContractError(
                f"{where}: {name} {record[name]!r} does not match {pattern.pattern}"
            )
    for name, allowed in contract.enums:
        if record[name] not in allowed:
            raise ContractError(f"{where}: invalid {name} {record[name]!r}")
    for name in sorted(contract.non_blank):
        if not str(record[name]).strip():
            raise ContractError(f"{where}: {name} must not be blank")
    return RuleSpec(**{field: record[field] for field in contract.fields})


def load_rule_catalog(path: Path, contract: RuleContract) -> tuple[RuleSpec, ...]:
    try:
        records = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ContractError(f"cannot read rule catalog {path}: {exc}") from exc
    if not isinstance(records, list) or not records:
        raise ContractError(f"{path} must contain a non-empty array of rules")

    specs = tuple(
        _validate_record(record, contract, f"{path}[{index}]")
        for index, record in enumerate(records)
    )
    seen: set[str] = set()
    for spec in specs:
        if spec.rule_id in seen:
            raise ContractError(f"{path}: duplicate rule_id {spec.rule_id}")
        seen.add(spec.rule_id)
    return specs


def canonical_catalog_text(specs: Iterable[RuleSpec]) -> str:
    """The one accepted serialization, so a hand edit either normalizes or fails a test."""
    return (
        json.dumps([spec.as_record() for spec in specs], indent=2, ensure_ascii=False) + "\n"
    )


def scalar_parameters(value: Any) -> list[str]:
    """Every string leaf of a `parameters` value, for the description-coherence check."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [leaf for item in value for leaf in scalar_parameters(item)]
    if isinstance(value, dict):
        return [leaf for item in value.values() for leaf in scalar_parameters(item)]
    raise ContractError(f"parameter values must be strings, lists or objects, not {type(value)}")


def bind_rules(
    specs: Iterable[RuleSpec],
    *,
    implementations: Mapping[str, RuleImplementation] | None = None,
    pending: Mapping[str, str] | None = None,
) -> dict[str, BoundRule]:
    """Bind every rule to its body, or to a declared reason it has none.

    Both maps are injectable so a falsification test can supply its own rather than mutating module
    state, which would leak between tests.
    """
    registered = RULE_IMPLEMENTATIONS if implementations is None else implementations
    waiting = PENDING_IMPLEMENTATIONS if pending is None else pending

    bound: dict[str, BoundRule] = {}
    by_canonical_field: dict[str, str] = {}
    for spec in specs:
        key = spec.implementation
        in_registered, in_waiting = key in registered, key in waiting
        if in_registered and in_waiting:
            raise ContractError(
                f"{spec.rule_id}: implementation {key!r} is both registered and declared pending"
            )
        if not in_registered and not in_waiting:
            raise ContractError(
                f"{spec.rule_id}: implementation {key!r} is neither registered nor declared "
                f"pending, so nothing states whether this rule runs"
            )

        implementation = registered.get(key)
        if implementation is not None:
            declared = set(spec.parameters)
            required = set(implementation.required_parameters)
            if declared != required:
                raise ContractError(
                    f"{spec.rule_id}: catalog declares parameters {sorted(declared)} but "
                    f"{key} requires exactly {sorted(required)}"
                )

        covered = (
            implementation.fields
            if implementation is not None and implementation.fields
            else (spec.field_name,)
        )
        if (
            implementation is not None
            and implementation.fields
            and spec.field_name not in implementation.fields
        ):
            raise ContractError(
                f"{spec.rule_id}: the catalog names field {spec.field_name!r} but {key} declares "
                f"it emits {list(implementation.fields)}, which does not include it"
            )
        for field in covered:
            if spec.status != ACTIVE_RULE_STATUS or field not in CANONICAL_COLUMNS:
                continue
            other = by_canonical_field.get(field)
            if other is not None:
                raise ContractError(
                    f"{field} has two active rules, {other} and {spec.rule_id}; the shipped "
                    f"provenance has exactly one winning rule per canonical field"
                )
            by_canonical_field[field] = spec.rule_id

        bound[spec.rule_id] = BoundRule(
            spec=spec,
            implementation=implementation,
            pending_reason="" if implementation is not None else waiting[key],
        )

    orphans = sorted(set(registered) - {spec.implementation for spec in specs})
    if orphans:
        raise ContractError(
            f"these implementations compute a value no published rule declares: {orphans}. A rule "
            f"table and the code it describes drifting apart is exactly backlog B18."
        )
    return bound


def assert_parameters_are_described(specs: Iterable[RuleSpec]) -> None:
    """Every declared parameter value must appear verbatim in its own rule description.

    A threshold that is prose in one place and data in another is how the published rule table came
    to disagree with the code it described (backlog B18, root cause R2). This is the check a
    parameter perturbation has to trip, which is what stops the catalog being decorative.
    """
    incoherent = {
        spec.rule_id: absent
        for spec in specs
        if (
            absent := [
                value
                for value in scalar_parameters(dict(spec.parameters))
                if value not in spec.description
            ]
        )
    }
    if incoherent:
        raise ContractError(
            f"declared parameters that do not appear in their own rule description: {incoherent}"
        )


# Decimal literals that appear in a rule description as *cited evidence* rather than as a declared
# threshold. Each is a measurement the description reports to justify a parameter, so it has no
# counterpart in `parameters` and must be named here or `assert_no_orphaned_thresholds` reads it as
# a threshold the rule stopped declaring.
#
# Keep this small and keep the reasons. An entry added to silence the check, rather than because the
# number really is a citation, converts the check back into the decoration it replaced.
CITED_MEASUREMENTS: dict[str, frozenset[str]] = {
    # The chunked-homogeneity guard's own calibration: the three broken windows that motivated the
    # floor sit at these internal deviations, and the next-highest genuine one at 8.1. They are the
    # evidence that the declared floor sits in a real gap rather than being fitted to three cases.
    "R-CLASS-2": frozenset({"21.5", "21.8", "55.2", "8.1"}),
}

_DECIMAL = re.compile(r"(?<![\d.])\d+\.\d+(?![\d.])")


def assert_no_orphaned_thresholds(specs: Iterable[RuleSpec]) -> None:
    """The converse of `assert_parameters_are_described`, and the half that was missing.

    That check is one-directional: every declared parameter must appear in the prose. It cannot see
    a parameter that *moves onto a value the prose already contains*. Measured — changing PV2's
    Sabin-like ceiling from 0.6 to 1.0 while the description still reads "below 0.6 percent for PV2"
    passes it, because "1.0" is already in the text for PV1 and PV3. 466 records reclassify and both
    gates stay green.

    What the mutation leaves behind is an orphan: "0.6" still stated in prose while no parameter
    declares it. So the rule is that every decimal literal in a description must be a declared value
    of that rule, unless it is named in `CITED_MEASUREMENTS` as a reported measurement. Both halves
    together mean the prose and the parameters have to move as one.
    """
    orphaned = {
        spec.rule_id: absent
        for spec in specs
        if (
            absent := sorted(
                {
                    literal
                    for literal in _DECIMAL.findall(spec.description)
                    if literal not in scalar_parameters(dict(spec.parameters))
                    and literal not in CITED_MEASUREMENTS.get(spec.rule_id, frozenset())
                }
            )
        )
    }
    if orphaned:
        raise ContractError(
            f"rule descriptions state decimal values their parameters do not declare: {orphaned}. "
            f"A threshold that moved leaves its old value stranded in prose; if these are reported "
            f"measurements rather than thresholds, name them in CITED_MEASUREMENTS with a reason."
        )


def assert_catalog_is_whole(specs: Sequence[RuleSpec]) -> None:
    """The count, the binding and the description coherence, over a catalog already loaded.

    Split out of `validate_rule_catalog` on 2026-08-12 so `build.py` can apply it to the catalog it
    has in hand rather than parsing the file a second time. Until then these ran *only* under
    `evgc validate-contracts` and pytest, so a build accepted a catalog whose declared thresholds
    did not appear in their own rule descriptions — the exact drift
    `assert_parameters_are_described` exists to catch, unchecked at the one moment it decides
    values. `bind_rules` was already called by the build; the other two were not.
    """
    if len(specs) != EXPECTED_RULE_COUNT:
        raise ContractError(
            f"{RULES_CATALOG_PATH} holds {len(specs)} rules; this release publishes "
            f"{EXPECTED_RULE_COUNT}"
        )
    bind_rules(specs)
    assert_parameters_are_described(specs)
    assert_no_orphaned_thresholds(specs)


def validate_rule_catalog(repository_root: Path) -> tuple[RuleSpec, ...]:
    """Shape, binding and description coherence, for `evgc validate-contracts`."""
    from enterovirus_genbank_curated.contracts import RULES_SCHEMA_PATH
    from enterovirus_genbank_curated.registry.implementations import load_rule_implementations

    load_rule_implementations()
    contract = load_rule_contract(repository_root / RULES_SCHEMA_PATH)
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    assert_catalog_is_whole(specs)
    return specs
