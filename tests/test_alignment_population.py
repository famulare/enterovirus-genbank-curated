"""The 1-to-1 claim: each alignment's row set is exactly what final metadata says it should be.

Every count here is **derived from the shipped metadata inside the test**, not asserted against a
literal copied from the same place it came from. Where a literal does appear it is a tripwire with
its derivation next to it, which is the repository's rule: no number without a derivation living
beside it.

The shipped alignments in `final/alignments/` are read here as a **comparison oracle only**. That is
what `docs/pipeline.md` boundary 1 permits — they are never pipeline inputs, and
`align.population` does not open them.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, population
from enterovirus_genbank_curated.contracts import ContractError

SHIPPED = "final/alignments/{name}.sto.gz"

# Deltas between the shipped artifacts and the metadata-derived populations, measured 2026-07-30.
# `added` rows are canonical records the shipped alignment lacks; `dropped` rows are shipped rows
# the rebuild legitimately loses. Both are re-derived per artifact in the delta tests, so these
# are tripwires: they fail when the underlying data moves, which is the point.
EXPECTED_DELTA = {
    "POLIO_unified": (98, 2),
    "NPEV_unified": (167, 0),
    "EV_unified": (263, 0),
    "PV1_unified": (715, 20),
    "PV2_unified": (358, 23),
    "PV3_unified": (270, 2),
}

# The two records whose `virus_group` changed since the shipped alignment was built. They are the
# only such records, so a silent regression here would look like a build bug rather than a data
# change — hence a named test.
RECLASSIFIED_TO_NON_POLIO = ("JX181922", "OR538735")

# Present in shipped PV3_unified, absent from canonical entirely: it carries an active
# `carve_exclusion` decision (D-9b532431747f). The 1-to-1 rule drops it with no special case.
CARVE_EXCLUDED_IN_SHIPPED = "AH004344"


def shipped_row_ids(repository_root: Path, name: str) -> frozenset[str]:
    """Row ids of a shipped Stockholm file. Oracle only."""
    ids: set[str] = set()
    with gzip.open(repository_root / SHIPPED.format(name=name), "rt", encoding="utf-8") as handle:
        for line in handle:
            line = line.rstrip("\n")
            if not line or line.startswith("#") or line == "//":
                continue
            ids.add(line.split(None, 1)[0])
    return frozenset(ids)


@pytest.fixture(scope="module")
def records(repository_root: Path) -> dict[str, population.AlignedRecord]:
    return population.load_all_records(repository_root)


@pytest.fixture(scope="module")
def populations(
    records: dict[str, population.AlignedRecord],
) -> dict[str, population.AlignmentPopulation]:
    return {name: population.select(records, spec) for name, spec in contract.ARTIFACTS.items()}


# --- membership is exactly what metadata says --------------------------------------------------


@pytest.mark.parametrize("name", sorted(contract.ARTIFACTS))
def test_membership_equals_the_metadata_filter_in_both_directions(
    records: dict[str, population.AlignedRecord], name: str
) -> None:
    spec = contract.ARTIFACTS[name]
    wanted_groups = set(spec.population.virus_groups)
    wanted_types = spec.population.virus_types
    expected = {
        key
        for key, record in records.items()
        if record.virus_group in wanted_groups
        and (wanted_types is None or record.virus_type in wanted_types)
    }
    actual = population.select(records, spec).accessions
    assert actual == expected, (
        f"{name}: {len(expected - actual)} metadata records missing, "
        f"{len(actual - expected)} extra"
    )


@pytest.mark.parametrize("name", sorted(contract.ARTIFACTS))
def test_the_declared_row_count_matches_the_derived_one(
    populations: dict[str, population.AlignmentPopulation], name: str
) -> None:
    """`expected_rows` is a tripwire. Recount it rather than trusting its own spelling."""
    pop = populations[name]
    assert len(pop.records) == pop.spec.expected_rows


def test_the_polio_partition_sums(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    """4,427 + 3,939 + 1,693 + 25 blanks = 10,084, derived rather than hardcoded."""
    per_type = sum(len(populations[f"PV{n}_unified"].records) for n in (1, 2, 3))
    blanks = sum(1 for r in populations["POLIO_unified"].records if not r.virus_type)
    assert per_type + blanks == len(populations["POLIO_unified"].records)


def test_ev_is_the_union_of_polio_and_npev(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    polio = populations["POLIO_unified"].accessions
    npev = populations["NPEV_unified"].accessions
    assert polio & npev == frozenset()
    assert populations["EV_unified"].accessions == polio | npev


def test_the_three_serotypes_partition_the_typed_polio_rows(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    sets = [populations[f"PV{n}_unified"].accessions for n in (1, 2, 3)]
    for i, left in enumerate(sets):
        for right in sets[i + 1 :]:
            assert left & right == frozenset()
    typed = {r.accession for r in populations["POLIO_unified"].records if r.virus_type}
    assert set().union(*sets) == typed


def test_every_row_id_is_version_stripped_and_unique(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    for name, pop in populations.items():
        ids = [r.accession for r in pop.records]
        assert len(ids) == len(set(ids)), f"{name} has duplicate row ids"
        assert not any("." in row_id for row_id in ids), f"{name} has a versioned row id"


def test_rows_are_in_declared_order(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    for name, pop in populations.items():
        keys = [(r.type_sort_key, r.accession) for r in pop.records]
        assert keys == sorted(keys), f"{name} rows are not in (type, accession) order"


# --- tiering ------------------------------------------------------------------------------------


def tier_by_column(
    repository_root: Path,
    records: dict[str, population.AlignedRecord],
    row_ids: frozenset[str],
    column: str,
) -> dict[str, int]:
    """Tier a row set using one fixed evidence column — the *shipped* partition's semantics.

    Needed because `population.tier_of` picks the column from canonical `virus_group`, and for two
    records canonical disagrees with the partition the shipped artifact was built under.
    """
    from enterovirus_genbank_curated.oracle.release import read_tsv_gz

    header, rows = read_tsv_gz(repository_root / contract.SEQUENCE_EVIDENCE)
    index = header.index(column)
    acc_index = header.index(contract.ACCESSION)
    confident = {
        population.base_accession(row[acc_index])
        for row in rows
        if row[index] == contract.BACKBONE_VALUE
    }
    backbone = len(row_ids & confident)
    return {"backbone": backbone, "addon": len(row_ids) - backbone}


@pytest.mark.parametrize(
    ("name", "column", "backbone", "addon"),
    [
        ("POLIO_unified", contract.SEROTYPE_CONFIDENT, 8736, 1252),
        ("NPEV_unified", contract.ENTEROVIRUS_TYPE_CONFIDENT, 10418, 3632),
    ],
)
def test_the_substituted_column_reproduces_the_shipped_tiers_exactly(
    repository_root: Path,
    records: dict[str, population.AlignedRecord],
    name: str,
    column: str,
    backbone: int,
    addon: int,
) -> None:
    """Under the shipped partition, this repo's evidence columns reproduce shipped tiers exactly.

    This is the port-fidelity evidence, and it needs no aligner: the shipped provenance records
    8,736/1,252 and 10,418/3,632, and `sequence_evidence.tsv.gz` reproduces both from a different
    column set than upstream's carve used. It is stated per *column* rather than via
    `population.tier_of`, because `tier_of` selects the column from canonical `virus_group` and for
    two records canonical disagrees with the partition the shipped file was built under — which the
    next test measures instead of glossing.
    """
    shipped = shipped_row_ids(repository_root, name)
    assert tier_by_column(repository_root, records, shipped, column) == {
        "backbone": backbone,
        "addon": addon,
    }


@pytest.mark.parametrize(
    ("name", "backbone", "addon"),
    [("POLIO_unified", 8737, 1251), ("NPEV_unified", 10418, 3632), ("EV_unified", 19155, 4883)],
)
def test_the_rebuilds_own_rule_differs_from_shipped_only_by_the_reclassified_records(
    repository_root: Path,
    records: dict[str, population.AlignedRecord],
    name: str,
    backbone: int,
    addon: int,
) -> None:
    """The rebuild keys the tier column on canonical `virus_group`, so two records change column.

    Shipped provenance: POLIO 8,736/1,252, NPEV 10,418/3,632, EV 19,154/4,884. Under the rebuild's
    rule POLIO becomes 8,737/1,251 and EV becomes 19,155/4,883, both by one record; NPEV is
    unaffected because neither reclassified record was in it. The mover is `JX181922`, whose two
    confidence columns disagree (`serotype_sequence_confident=FALSE`,
    `enterovirus_type_sequence_confident=TRUE`), so switching which column governs flips it
    backbone-ward. Deriving this is honest; asserting exactness on all three would assert something
    false.
    """
    shipped = shipped_row_ids(repository_root, name)
    counts = {"backbone": 0, "addon": 0}
    for row_id in shipped:
        counts[records[row_id].tier] += 1
    assert counts == {"backbone": backbone, "addon": addon}


def test_the_tier_difference_is_attributable_to_jx181922(
    repository_root: Path, records: dict[str, population.AlignedRecord]
) -> None:
    """Name the record, so the +1/-1 above is explained rather than merely measured."""
    shipped_polio = shipped_row_ids(repository_root, "POLIO_unified")
    movers = [
        row_id
        for row_id in shipped_polio
        if records[row_id].virus_group != contract.POLIOVIRUS
        and records[row_id].tier == "backbone"
    ]
    assert movers == ["JX181922"]


def test_a_blank_confidence_value_falls_to_addon(
    records: dict[str, population.AlignedRecord],
) -> None:
    """The third state: 125 non-polio records have a blank confidence column, not FALSE."""
    row = {
        contract.ACCESSION: "X",
        contract.VIRUS_GROUP: contract.NON_POLIO,
    }
    assert population.tier_of(row, {contract.ENTEROVIRUS_TYPE_CONFIDENT: ""}) == "addon"
    assert population.tier_of(row, None) == "addon"
    assert population.tier_of(row, {contract.ENTEROVIRUS_TYPE_CONFIDENT: "TRUE"}) == "backbone"


def test_an_unknown_virus_group_is_refused() -> None:
    with pytest.raises(ContractError, match="unknown virus_group"):
        population.tier_of({contract.ACCESSION: "X", contract.VIRUS_GROUP: "martian"}, None)


# --- the delta against the shipped artifacts ----------------------------------------------------


@pytest.mark.parametrize("name", sorted(contract.ARTIFACTS))
def test_the_delta_against_the_shipped_artifact_is_exactly_as_declared(
    repository_root: Path,
    populations: dict[str, population.AlignmentPopulation],
    name: str,
) -> None:
    shipped = shipped_row_ids(repository_root, name)
    rebuilt = populations[name].accessions
    added, dropped = EXPECTED_DELTA[name]
    assert len(rebuilt - shipped) == added, f"{name}: added set changed"
    assert len(shipped - rebuilt) == dropped, f"{name}: dropped set changed"


def test_every_dropped_pv_row_has_a_reason_in_the_closed_vocabulary(
    repository_root: Path,
    records: dict[str, population.AlignedRecord],
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    """45 shipped PV rows leave. Adjudicated is not invisible: each needs a classifiable reason."""
    reasons: dict[str, str] = {}
    for n in (1, 2, 3):
        name = f"PV{n}_unified"
        for row_id in shipped_row_ids(repository_root, name) - populations[name].accessions:
            record = records.get(row_id)
            if record is None:
                reasons[row_id] = "carve_excluded"
            elif record.virus_group != contract.POLIOVIRUS:
                reasons[row_id] = "group_moved"
            elif not record.virus_type:
                reasons[row_id] = "virus_type_lost"
            else:
                reasons[row_id] = "serotype_relabelled"
    assert len(reasons) == 45
    assert set(reasons.values()) <= set(contract.DROP_REASONS)
    tally = {
        reason: sum(1 for v in reasons.values() if v == reason) for reason in set(reasons.values())
    }
    # Reasons are assigned most-specific first, so `OR538735` — which both changed group and lost
    # its type — counts once, as `group_moved`. That is why this is 2/10 and not 1/11: the two
    # classifications overlap on one record, and the precedence is declared rather than incidental.
    assert tally == {
        "serotype_relabelled": 32,
        "virus_type_lost": 10,
        "group_moved": 2,
        "carve_excluded": 1,
    }
    assert sum(tally.values()) == 45
    assert reasons[CARVE_EXCLUDED_IN_SHIPPED] == "carve_excluded"
    for accession in RECLASSIFIED_TO_NON_POLIO:
        assert reasons.get(accession) == "group_moved"


def test_the_reclassified_records_move_to_npev(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    """The only two records whose group changed. A regression here mimics a build bug."""
    polio = populations["POLIO_unified"].accessions
    npev = populations["NPEV_unified"].accessions
    for accession in RECLASSIFIED_TO_NON_POLIO:
        assert accession in npev, f"{accession} should now be non-polio"
        assert accession not in polio, f"{accession} should have left the polio partition"


# --- family rule --------------------------------------------------------------------------------


def test_the_family_rule_is_upstreams_including_the_echo_fallback() -> None:
    assert contract.family_of("") == "unknown"
    assert contract.family_of("PV1") == "PV"
    assert contract.family_of("CVA24") == "CVA"
    assert contract.family_of("CVB3") == "CVB"
    assert contract.family_of("EV-D68") == "EV-D"
    assert contract.family_of("RV-C40") == "RV-C"
    # The fallback that a rule reconstructed from counts alone would get wrong.
    assert contract.family_of("E6") == "Echo"
    assert contract.family_of("E30") == "Echo"


def test_the_family_rule_reproduces_the_shipped_counts_given_the_shipped_rows(
    repository_root: Path, records: dict[str, population.AlignedRecord]
) -> None:
    """Divergence from the shipped `families` block is attributable to the type column alone.

    Same rule, same rows, richer input: canonical `virus_type` resolves records upstream left blank,
    so `unknown` shrinks and the resolved families grow by exactly that much.
    """
    shipped = shipped_row_ids(repository_root, "NPEV_unified")
    counts: dict[str, int] = {}
    for row_id in shipped:
        family = records[row_id].family
        counts[family] = counts.get(family, 0) + 1
    shipped_families = {
        "CVA": 6191, "Echo": 2629, "unknown": 1277, "EV-D": 948, "CVB": 897,
        "EV-C": 701, "EV-A": 377, "RV-C": 347, "RV-A": 344, "EV-B": 227, "RV-B": 112,
    }
    assert sum(counts.values()) == sum(shipped_families.values())
    # Families upstream and canonical agree on exactly.
    for family in ("EV-A", "EV-D", "RV-A", "RV-B", "RV-C"):
        assert counts[family] == shipped_families[family], family
    # Everything gained is exactly what `unknown` lost.
    gained = sum(counts[f] - shipped_families[f] for f in counts if counts[f] > shipped_families[f])
    assert gained == shipped_families["unknown"] - counts["unknown"]


# --- the blank-type sentinel ---------------------------------------------------------------------


def test_blank_types_take_the_sentinel_for_their_own_group(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    """Regression: a shared sentinel labelled 877 non-polio rows `PV?`, asserting they are polio."""
    polio_blanks = [r for r in populations["POLIO_unified"].records if not r.virus_type]
    npev_blanks = [r for r in populations["NPEV_unified"].records if not r.virus_type]
    assert {r.type_sort_key for r in polio_blanks} == {"PV?"}
    assert {r.type_sort_key for r in npev_blanks} == {"unknown"}
    assert len(polio_blanks) == 25
    assert len(npev_blanks) == 877
    ev_labels = populations["EV_unified"].type_counts()
    assert ev_labels["PV?"] == 25
    assert ev_labels["unknown"] == 877


def test_the_blank_polio_records_are_in_no_serotype_artifact(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    blanks = {r.accession for r in populations["POLIO_unified"].records if not r.virus_type}
    for n in (1, 2, 3):
        assert blanks & populations[f"PV{n}_unified"].accessions == frozenset()


# --- the population digest ----------------------------------------------------------------------


def test_the_digest_depends_only_on_membership(
    records: dict[str, population.AlignedRecord],
) -> None:
    spec = contract.ARTIFACTS["PV3_unified"]
    first = population.select(records, spec).digest()
    shuffled = dict(reversed(list(records.items())))
    assert population.select(shuffled, spec).digest() == first


def test_the_digest_changes_when_membership_changes(
    records: dict[str, population.AlignedRecord],
) -> None:
    spec = contract.ARTIFACTS["PV3_unified"]
    before = population.select(records, spec).digest()
    trimmed = dict(records)
    victim = next(k for k, r in trimmed.items() if r.virus_type == "PV3")
    del trimmed[victim]
    assert population.select(trimmed, spec).digest() != before


# --- fail-closed checks ---------------------------------------------------------------------------


def test_an_unknown_artifact_name_is_refused(repository_root: Path) -> None:
    with pytest.raises(ContractError, match="unknown alignment"):
        population.load_population(repository_root, "PV9_unified")


def test_a_sequence_absent_from_the_fasta_is_refused(
    repository_root: Path, monkeypatch
) -> None:
    """A record in metadata with no sequence would silently shrink the population."""
    monkeypatch.setattr(population, "load_sequences", lambda _path: {})
    with pytest.raises(ContractError, match="the population would not be 1-to-1"):
        population.load_all_records(repository_root)


def test_a_length_disagreement_between_fasta_and_metadata_is_refused(
    repository_root: Path, monkeypatch
) -> None:
    """Guards the join itself: a truncated FASTA record must fail, not quietly align short."""
    real = population.load_sequences

    def truncated(path: Path) -> dict[str, str]:
        sequences = real(path)
        victim = next(iter(sorted(sequences)))
        sequences[victim] = sequences[victim][:-1]
        return sequences

    monkeypatch.setattr(population, "load_sequences", truncated)
    with pytest.raises(ContractError, match="declares"):
        population.load_all_records(repository_root)
