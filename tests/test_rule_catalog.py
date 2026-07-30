"""The rule catalog, and the checks that make it more than decorative.

`registry/schemas/rules.schema.json` had no instance until now (backlog B17/B18), so none of its
constraints had ever rejected anything. Every test below mutates a copy of the real catalog and
asserts that validation notices — the same method `tests/test_parity_spec.py` applies to the parity
contract, for the same reason: a contract nothing can contradict is not a contract.

The load-bearing test is `test_the_catalog_regenerates_the_shipped_rules_table_byte_for_byte`. It is
what makes the catalog demonstrably a description of the release rather than a plausible-looking
file next to it, and it is why the parameter mutation test can be trusted: perturb a threshold and a
real gate goes red.
"""

from __future__ import annotations

import copy
import gzip
import json
from pathlib import Path
from typing import Any

import pytest

from enterovirus_genbank_curated.contracts import RULES_SCHEMA_PATH, ContractError
from enterovirus_genbank_curated.export.audit import RULES_VIEW_RELATIVE, write_rules_view
from enterovirus_genbank_curated.registry.implementations import load_rule_implementations
from enterovirus_genbank_curated.registry.rules import (
    EXPECTED_RULE_COUNT,
    RULE_FIELD_ORDER,
    RULE_IMPLEMENTATIONS,
    RULES_CATALOG_PATH,
    RuleImplementation,
    assert_parameters_are_described,
    bind_rules,
    canonical_catalog_text,
    load_rule_catalog,
    load_rule_contract,
    scalar_parameters,
    validate_rule_catalog,
)

SHIPPED_RULES = "final/audit/rules.tsv.gz"


@pytest.fixture(scope="module")
def contract(repository_root: Path):
    return load_rule_contract(repository_root / RULES_SCHEMA_PATH)


@pytest.fixture(scope="module")
def records(repository_root: Path) -> list[dict[str, Any]]:
    return json.loads((repository_root / RULES_CATALOG_PATH).read_text(encoding="utf-8"))


def write_catalog(tmp_path: Path, records: list[dict[str, Any]]) -> Path:
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def mutated(records: list[dict[str, Any]], index: int, **changes: Any) -> list[dict[str, Any]]:
    out = copy.deepcopy(records)
    out[index].update(changes)
    return out


def test_the_real_catalog_validates(repository_root: Path) -> None:
    specs = validate_rule_catalog(repository_root)
    assert len(specs) == EXPECTED_RULE_COUNT


def test_the_catalog_regenerates_the_shipped_rules_table_byte_for_byte(
    repository_root: Path, contract, tmp_path: Path
) -> None:
    """The gate. Four of the catalog's seven fields are a projection of a frozen artifact."""
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    write_rules_view(tmp_path, specs)
    assert (tmp_path / RULES_VIEW_RELATIVE).read_bytes() == (
        repository_root / SHIPPED_RULES
    ).read_bytes()


def test_the_catalog_is_its_own_canonical_serialization(
    repository_root: Path, contract
) -> None:
    """So a hand edit either normalizes or fails, rather than drifting the formatting."""
    path = repository_root / RULES_CATALOG_PATH
    specs = load_rule_catalog(path, contract)
    assert path.read_text(encoding="utf-8") == canonical_catalog_text(specs)


def test_every_declared_parameter_appears_in_its_own_description(
    repository_root: Path, contract
) -> None:
    """Root cause R2: prose and data drift, and the prose is always the optimistic one."""
    for spec in load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract):
        for value in scalar_parameters(dict(spec.parameters)):
            assert value in spec.description, f"{spec.rule_id}: {value!r} is not in its description"


# --- falsification: each mutation must be refused -------------------------------------------------


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({"rule_id": "r-lowercase-1"}, "does not match"),
        ({"rule_id": "SCOPE-1"}, "does not match"),
        ({"rule_version": "2.4"}, "does not match"),
        ({"rule_version": "v2.4.1"}, "does not match"),
        ({"status": "retired"}, "invalid status"),
        ({"field_name": ""}, "must not be blank"),
        ({"description": ""}, "must not be blank"),
        ({"parameters": "0.15"}, "parameters must be an object"),
    ],
)
def test_a_record_violating_the_schema_is_refused(
    records: list[dict[str, Any]], contract, tmp_path: Path, changes: dict[str, Any], expected: str
) -> None:
    path = write_catalog(tmp_path, mutated(records, 0, **changes))
    with pytest.raises(ContractError, match=expected):
        load_rule_catalog(path, contract)


def test_an_undeclared_property_is_refused(
    records: list[dict[str, Any]], contract, tmp_path: Path
) -> None:
    """`additionalProperties: false` in the schema, enforced here for the first time."""
    path = write_catalog(tmp_path, mutated(records, 0, owner="nobody"))
    with pytest.raises(ContractError, match="undeclared fields"):
        load_rule_catalog(path, contract)


def test_a_missing_required_field_is_refused(
    records: list[dict[str, Any]], contract, tmp_path: Path
) -> None:
    trimmed = copy.deepcopy(records)
    del trimmed[0]["implementation"]
    path = write_catalog(tmp_path, trimmed)
    with pytest.raises(ContractError, match="missing fields"):
        load_rule_catalog(path, contract)


def test_a_duplicate_rule_id_is_refused(
    records: list[dict[str, Any]], contract, tmp_path: Path
) -> None:
    doubled = copy.deepcopy(records)
    doubled.append(copy.deepcopy(doubled[0]))
    path = write_catalog(tmp_path, doubled)
    with pytest.raises(ContractError, match="duplicate rule_id"):
        load_rule_catalog(path, contract)


def test_an_unbound_implementation_key_is_refused(
    repository_root: Path, contract
) -> None:
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    with pytest.raises(ContractError, match="neither registered nor declared"):
        bind_rules(specs, implementations={}, pending={})


def test_a_key_that_is_both_registered_and_pending_is_refused(
    repository_root: Path, contract
) -> None:
    """An ambiguous state: the same rule would both run and be excused from running."""
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    key = specs[0].implementation
    fake = RuleImplementation(
        key=key,
        required_parameters=frozenset(specs[0].parameters),
        declared_bases=frozenset({"x"}),
        fn=lambda *a, **k: None,
    )
    with pytest.raises(ContractError, match="both registered and declared pending"):
        bind_rules(specs, implementations={key: fake}, pending={key: "also pending"})


def test_an_implementation_no_rule_declares_is_refused(
    repository_root: Path, contract
) -> None:
    """The direction that catches B18: code computing a value the rule table never published.

    The real registrations are kept, so the orphan is the *only* anomaly — otherwise the genuinely
    bound rules would trip the unbound-key check first and the test would pass for the wrong reason.
    """
    load_rule_implementations()
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    orphan = RuleImplementation(
        key="derive.nowhere.orphan",
        required_parameters=frozenset(),
        declared_bases=frozenset(),
        fn=lambda *a, **k: None,
    )
    with pytest.raises(ContractError, match="no published rule declares"):
        bind_rules(specs, implementations={**RULE_IMPLEMENTATIONS, orphan.key: orphan})


def test_a_parameter_set_that_disagrees_with_its_implementation_is_refused(
    repository_root: Path, contract
) -> None:
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    target = next(s for s in specs if s.parameters)
    implementation = RuleImplementation(
        key=target.implementation,
        required_parameters=frozenset({"a_parameter_the_catalog_does_not_declare"}),
        declared_bases=frozenset(),
        fn=lambda *a, **k: None,
    )
    pending = {s.implementation: "pending" for s in specs if s is not target}
    with pytest.raises(ContractError, match="requires exactly"):
        bind_rules(specs, implementations={implementation.key: implementation}, pending=pending)


def test_two_active_rules_for_one_canonical_field_are_refused(
    records: list[dict[str, Any]], contract, tmp_path: Path
) -> None:
    """The shipped provenance has exactly one winning rule per canonical field."""
    doubled = copy.deepcopy(records)
    clone = copy.deepcopy(next(r for r in doubled if r["field_name"] == "sequence_scope"))
    clone["rule_id"] = "R-SCOPE-2"
    doubled.append(clone)
    specs = load_rule_catalog(write_catalog(tmp_path, doubled), contract)
    with pytest.raises(ContractError, match="two active rules"):
        bind_rules(specs)


def test_perturbing_a_threshold_turns_a_real_gate_red(
    records: list[dict[str, Any]], contract, tmp_path: Path
) -> None:
    """Without this, assume the catalog is decorative.

    A published parameter that no gate depends on is documentation with extra steps. Changing
    `wild_threshold` must break something: here the description-coherence check, which is what ties
    the declared value to the rule's own published prose.
    """
    perturbed = copy.deepcopy(records)
    target = next(r for r in perturbed if r["rule_id"] == "R-TIER-WILD-1")
    assert target["parameters"]["wild_threshold"] == "0.15"
    target["parameters"]["wild_threshold"] = "0.16"

    specs = load_rule_catalog(write_catalog(tmp_path, perturbed), contract)
    with pytest.raises(ContractError, match="do not appear in their own rule description"):
        assert_parameters_are_described(specs)


def test_the_declared_field_order_is_the_schemas_required_order(contract) -> None:
    assert contract.fields == RULE_FIELD_ORDER


def test_the_shipped_view_has_no_rule_the_catalog_omits(
    repository_root: Path, contract
) -> None:
    """Both directions, so neither a dropped nor an invented rule passes."""
    specs = load_rule_catalog(repository_root / RULES_CATALOG_PATH, contract)
    with gzip.open(repository_root / SHIPPED_RULES, "rt", encoding="utf-8") as handle:
        shipped_ids = [line.split("\t")[0] for line in handle.read().splitlines()[1:]]
    assert [s.rule_id for s in specs] == shipped_ids
