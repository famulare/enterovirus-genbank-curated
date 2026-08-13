"""The 2.4.1 canonical baseline, and the transition contract measured against it.

## Why a fixture of a superseded release exists at all

`final/` is this pipeline's own output, so nothing in the tree could any longer answer "what changed
between the last hand-curated release and what we build?". That question stopped being answerable on
2026-08-01, and two declared deltas drifted while it was: the date-family delta moved 4,549 -> 4,564
behind `SUPERSEDED_FIELD_DELTAS`, a gate that had been deleted, and the classification migration-gap
document lost two records out of a categorisation whose whole claim was that it had no residue.

It has since earned its keep the other way round, twice. `sequence_scope` and `collection_date` were
both recorded as unreachable from `raw/`; both were reproduced against this fixture and both are now
absent from the transition contract entirely. A comparand is also how you find out that a declared
gap was a mis-specification.

`releases/2.4.1/canonical/sequence_metadata.tsv.gz` is the answer, preserved once. It is a fixture:
read by `oracle/parity.py` and by these tests, by nothing else, and never by a build —
`sandbox.READ_REFUSED_DIRS` names its directory so that is enforced rather than asserted. It is not
a parity target, because 2.4.1 is superseded and reproducing it is not a goal, so the claim it
supports does not weaken as the pipeline improves: *every* cell that differs belongs to a class
somebody declared.

## Why the hash is not pinned here

An earlier draft hard-coded the digest in this file. It did not need to.
`releases/2.4.1/parity.json` — the immutable contract for that release — already declares the
sha256 of its own `final/canonical/sequence_metadata.tsv.gz`, and the preserved fixture is
byte-identical to it. So the fixture is authenticated by the release's own contract rather than by
a number somebody typed here, and `expected_artifacts` gains its first live consumer since the
2026-08-01 promotion retired `verify_expected_artifacts`.

## Tiering

Everything here is fast except one test. `compare_to_baseline` is pure, so the falsification battery
mutates the declarations and watches it go red against the committed `final/` table in milliseconds.
The single slow test is the one that cannot be faked: it drives the real CLI verb, in its guarded
form, over a real 25,727-record rebuild.
"""

from __future__ import annotations

import gzip
import subprocess
import sys
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import (
    CANONICAL_COLUMNS,
    PARITY_SPEC_PATH,
    ContractError,
    load_json,
    sha256_file,
)
from enterovirus_genbank_curated.export.canonical import read_canonical_table
from enterovirus_genbank_curated.oracle.parity import (
    BASELINE_CANONICAL,
    DECLARED_ROW_DELTA,
    DECLARED_TRANSITIONS,
    compare_to_baseline,
    load_baseline_canonical,
    measure_transitions,
)

BASELINE_ROWS = 24301
SHIPPED_CANONICAL_IN_PARITY_SPEC = "final/canonical/sequence_metadata.tsv.gz"


@pytest.fixture(scope="module")
def baseline(repository_root: Path) -> dict[str, dict[str, str]]:
    return load_baseline_canonical(repository_root)


@pytest.fixture(scope="module")
def built(repository_root: Path) -> dict[str, dict[str, str]]:
    """The committed release, read as-is.

    Standing in for a rebuild is legitimate here and only here: `tests/test_release_integrity.py`
    already refuses a `final/` whose `code_sha256` does not name the committed code, so these bytes
    are this code's output. The slow test below pays for the real rebuild.
    """
    return {row["version"]: row for row in read_canonical_table(repository_root / "final")}


# --- the fixture itself --------------------------------------------------------------------


def test_the_baseline_fixture_is_the_release_its_own_contract_declares(
    repository_root: Path,
) -> None:
    """Authenticated against `releases/2.4.1/parity.json`, not against a number typed here."""
    target = repository_root / BASELINE_CANONICAL
    assert target.is_file(), f"{BASELINE_CANONICAL} is missing; the transition gate has no baseline"
    spec = load_json(repository_root / PARITY_SPEC_PATH)
    declared = [
        artifact["sha256"]
        for artifact in spec["expected_artifacts"]
        if artifact["path"] == SHIPPED_CANONICAL_IN_PARITY_SPEC
    ]
    assert declared, (
        f"{PARITY_SPEC_PATH} no longer declares {SHIPPED_CANONICAL_IN_PARITY_SPEC}; the preserved "
        f"baseline has lost the contract that authenticates it"
    )
    assert sha256_file(target) == declared[0]


def test_the_baseline_is_the_shape_2_4_1_shipped(baseline: dict[str, dict[str, str]]) -> None:
    assert len(baseline) == BASELINE_ROWS
    assert {column for row in baseline.values() for column in row} == set(CANONICAL_COLUMNS)


def test_the_guard_refuses_a_read_of_the_baseline(repository_root: Path) -> None:
    """The fixture is a previous release's answer key; the guard has to refuse it at runtime.

    `final/` is refused for exactly this property and a preserved canonical table has it too: a
    build that reads the last release's answers can reproduce them perfectly and prove nothing.
    The parent cannot be refused — `contracts.py` reads `releases/2.4.1/parity.json` on every build
    to authenticate the raw archive — so the refusal is pinned to the one subtree a build never
    needs.

    Composed segment-wise on purpose, following `test_the_guard_refuses_a_read_of_the_legacy_
    directory`: the audit hook keys on the resolved path, so this spelling is covered where a grep
    for the literal would not see it.
    """
    probe = (
        "from pathlib import Path\n"
        "from enterovirus_genbank_curated.sandbox import install_input_guard\n"
        f"root = Path({str(repository_root)!r})\n"
        "install_input_guard(root)\n"
        "target = root / 'releases' / '2.4.1' / 'canonical' / 'sequence_metadata.tsv.gz'\n"
        "target.open('rb').read(1)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=repository_root
    )
    assert result.returncode != 0, (
        "a guarded build read the preserved 2.4.1 canonical table without complaint. That table is "
        "the comparison baseline; a build that can read it can reproduce it and prove nothing."
    )
    assert "UndeclaredInputError" in result.stderr, result.stderr
    assert "releases/2.4.1/canonical" in result.stderr, result.stderr


def test_the_baseline_guard_can_fail(repository_root: Path) -> None:
    """Negative control: the parity spec beside it stays readable.

    Without this, a guard that refused every read under `releases/` would satisfy the test above
    while saying nothing — and it would also break every build, since `contracts.py` reads
    `parity.json` to authenticate the raw archive.
    """
    probe = (
        "from pathlib import Path\n"
        "from enterovirus_genbank_curated.sandbox import install_input_guard\n"
        f"root = Path({str(repository_root)!r})\n"
        "install_input_guard(root)\n"
        "(root / 'releases' / '2.4.1' / 'parity.json').open(encoding='utf-8').readline()\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, cwd=repository_root
    )
    assert result.returncode == 0, result.stderr


# --- the pure comparison, and what makes it fail ---------------------------------------------


def test_measure_transitions_counts_only_differing_cells() -> None:
    before = {"A.1": {"colour": "red", "shape": "round"}}
    after = {"A.1": {"colour": "blue", "shape": "round"}}
    assert measure_transitions(before, after) == {"colour": {("red", "blue"): 1}}


def test_measure_transitions_ignores_rows_only_one_side_has() -> None:
    """The row-set delta is declared separately; it must not leak into the cell tallies."""
    before = {"A.1": {"colour": "red"}, "GONE.1": {"colour": "red"}}
    after = {"A.1": {"colour": "red"}, "NEW.1": {"colour": "green"}}
    assert measure_transitions(before, after) == {}


def test_the_committed_release_differs_from_the_baseline_only_in_declared_ways(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]]
) -> None:
    assert compare_to_baseline(baseline, built) == {
        column: dict(classes) for column, classes in DECLARED_TRANSITIONS.items()
    }


def test_a_deleted_transition_class_fails(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]], monkeypatch
) -> None:
    """Deleting a class is the cheapest proof the comparison is real.

    The build still produces those cells, so a gate that only checked the classes it knows about
    would stay green.
    """
    import enterovirus_genbank_curated.oracle.parity as parity

    mutated = {
        column: (dict(classes) if column != "engineered_or_construct" else {})
        for column, classes in DECLARED_TRANSITIONS.items()
    }
    monkeypatch.setattr(parity, "DECLARED_TRANSITIONS", mutated)
    with pytest.raises(ContractError, match="engineered_or_construct"):
        compare_to_baseline(baseline, built)


def test_a_moved_count_fails(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]], monkeypatch
) -> None:
    import enterovirus_genbank_curated.oracle.parity as parity

    mutated = {column: dict(classes) for column, classes in DECLARED_TRANSITIONS.items()}
    mutated["engineered_or_construct"][("TRUE", "FALSE")] += 1
    monkeypatch.setattr(parity, "DECLARED_TRANSITIONS", mutated)
    with pytest.raises(ContractError, match="declared 512"):
        compare_to_baseline(baseline, built)


def test_relocating_a_blanking_onto_a_different_record_fails(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]]
) -> None:
    """Why the from-side is enumerated per value instead of folded to a wildcard.

    This mutation moves one blanking from a `CVA13` record to a `CVA24` one, leaving the column's
    total difference count untouched. Folding the from-side to a wildcard was tried, and it passed
    green — only totals were checked, so a mis-scoped rule could redistribute a whole population
    silently. Enumerating the from-value is what makes it fail.

    It was `collection_date` that proved this, over 59 per-year classes. That column now agrees with
    the baseline exactly, so the check moved to `virus_type` rather than retiring with it — the
    property is about the shape of the contract, not about dates.
    """
    moved = {version: dict(row) for version, row in built.items()}

    def pick(value: str, *, agreeing: bool) -> str:
        return next(
            version
            for version in moved
            if baseline.get(version, {}).get("virus_type") == value
            and (moved[version]["virus_type"] == value) is agreeing
        )

    donor = pick("CVA13", agreeing=False)
    taker = pick("CVA24", agreeing=True)
    moved[donor]["virus_type"] = baseline[donor]["virus_type"]
    moved[taker]["virus_type"] = ""
    with pytest.raises(ContractError, match="virus_type"):
        compare_to_baseline(baseline, moved)


def test_a_moved_carve_delta_fails(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]], monkeypatch
) -> None:
    import enterovirus_genbank_curated.oracle.parity as parity

    monkeypatch.setattr(
        parity, "DECLARED_ROW_DELTA", {"added": DECLARED_ROW_DELTA["added"], "dropped": ()}
    )
    with pytest.raises(ContractError, match="carve delta"):
        compare_to_baseline(baseline, built)


def test_a_dropped_column_fails_rather_than_going_uncompared(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]]
) -> None:
    """A column missing from the build must be reported, not silently left out of the join."""
    stripped = {
        version: {k: v for k, v in row.items() if k != "specimen_type"}
        for version, row in built.items()
    }
    with pytest.raises(ContractError, match="specimen_type"):
        compare_to_baseline(baseline, stripped)


def test_an_empty_build_fails(baseline: dict[str, dict[str, str]]) -> None:
    """A gate that reports success having compared nothing is the failure mode this repo hunts."""
    with pytest.raises(ContractError):
        compare_to_baseline(baseline, {})


def test_an_empty_baseline_fails(built: dict[str, dict[str, str]]) -> None:
    with pytest.raises(ContractError):
        compare_to_baseline({}, built)


def test_a_truncated_baseline_fails(
    repository_root: Path, built: dict[str, dict[str, str]], tmp_path: Path, monkeypatch
) -> None:
    """Half a fixture is the one corruption that still has the right column set."""
    source = repository_root / BASELINE_CANONICAL
    with gzip.open(source, "rt", encoding="utf-8", newline="") as handle:
        lines = handle.readlines()
    truncated = tmp_path / BASELINE_CANONICAL
    truncated.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(truncated, "wt", encoding="utf-8", newline="") as handle:
        handle.writelines(lines[: len(lines) // 2])
    with pytest.raises(ContractError):
        compare_to_baseline(load_baseline_canonical(tmp_path), built)


# --- declarations that have to name real things ----------------------------------------------


def test_every_declared_column_is_a_canonical_column() -> None:
    undeclared = sorted(set(DECLARED_TRANSITIONS) - set(CANONICAL_COLUMNS))
    assert not undeclared, f"transitions declared for non-canonical columns: {undeclared}"


def test_the_declared_row_delta_names_versions_that_exist(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]]
) -> None:
    """A typo in either tuple would otherwise sit there looking like a declaration."""
    for version in DECLARED_ROW_DELTA["dropped"]:
        assert version in baseline, f"{version} is declared dropped but 2.4.1 does not carry it"
        assert version not in built, f"{version} is declared dropped but the build carries it"
    for version in DECLARED_ROW_DELTA["added"]:
        assert version not in baseline, f"{version} is declared added but 2.4.1 already carries it"
        assert version in built, f"{version} is declared added but the build does not carry it"


def test_the_documented_date_break_is_the_declared_one(
    baseline: dict[str, dict[str, str]], built: dict[str, dict[str, str]]
) -> None:
    """The delta `docs/reproducibility.md` calls "the first deliberate break", pinned by name.

    This existed once as `SUPERSEDED_FIELD_DELTAS` and was deleted in `c245dd3`, while the prose
    kept saying the numbers were "declared in `oracle/parity.py` and required to match exactly, so
    a deliberate delta changing size fails the gate". No such gate remained, and the delta did
    change size — 4,549 -> 4,564 — with nothing to notice.

    Restored as part of `DECLARED_TRANSITIONS` rather than as a parallel constant, so there is one
    contract rather than two that can disagree. Named here so the documented numbers have a
    locatable referent and the prose cannot drift from the check again.

    **What the break now is.** Half of it went away on 2026-08-12: the 1,761 records that lost a
    date were the ones whose year 2.4.1 attributed to a source outside GenBank, and every one of
    them turned out to be readable from a surveillance identifier in `raw/`. So `collection_date`
    has no declared class at all, and that is asserted here rather than merely left out — a column
    quietly reappearing in this contract is the regression to catch. What remains is the vocabulary
    break: 2,803 dateless records whose precision was `unknown` and is now `NA`.
    """
    assert "collection_date" not in DECLARED_TRANSITIONS, (
        "collection_date has a declared difference from 2.4.1 again; R-DATE-2's identifier branch "
        "reproduced that column exactly, so a new class here is a regression and not a declaration"
    )
    precision = DECLARED_TRANSITIONS["collection_date_precision"]
    assert precision == {("unknown", "NA"): 2803}

    # Measured rather than inferred from the absence above: every shared row agrees on the date.
    # Which of them agree *because* of the identifier branch is pinned per convention in
    # `tests/test_date_identifiers.py`, against the shipped provenance that names it.
    shared = set(baseline) & set(built)
    assert not [v for v in shared if baseline[v]["collection_date"] != built[v]["collection_date"]]

    # Both halves of the invariant the remaining break rests on: a precision difference is always
    # `unknown` -> `NA`, and it lands only on rows blank on both sides.
    assert all(before == "unknown" and after == "NA" for before, after in precision)
    assert not [
        v
        for v in shared
        if built[v]["collection_date_precision"] == "NA" and built[v]["collection_date"]
    ]


# --- the one thing that cannot be faked --------------------------------------------------------


@pytest.mark.slow
def test_the_guarded_cli_verb_runs_the_real_build_and_passes(
    repository_root: Path, capsys
) -> None:
    """Covers the CLI branch, the guarded child, and a real 25,727-record rebuild in one test.

    Everything above compares the *committed* `final/`, which is fast and sufficient for the
    comparison logic but says nothing about the plumbing that produces the table being compared.
    This is that plumbing, driven the way CI and a human actually invoke it.
    """
    from enterovirus_genbank_curated import cli

    assert cli.main(["parity-canonical", "--guard-inputs", "--repository-root",
                     str(repository_root)]) == 0
    out = capsys.readouterr().out
    assert "canonical transitions: PASS" in out
    assert cli.GUARD_PASS_LINE in out
