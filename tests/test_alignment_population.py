"""The 1-to-1 claim: each alignment's row set is exactly what final metadata says it should be.

Every count here is **derived from the shipped metadata inside the test**, not asserted against a
literal copied from the same place it came from. Where a literal does appear it is a tripwire with
its derivation next to it, which is the repository's rule: no number without a derivation living
beside it.

The 2.4.1 alignments in `releases/2.4.1/alignments/` are read here as a **comparison oracle
only** — they moved out of `final/` when the natively-built set was promoted into it. That is
what `docs/pipeline.md` boundary 1 permits — they are never pipeline inputs, and
`align.population` does not open them.
"""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from enterovirus_genbank_curated.align import contract, population
from enterovirus_genbank_curated.contracts import ContractError
from enterovirus_genbank_curated.oracle.parity import load_baseline_canonical

SHIPPED = "releases/2.4.1/alignments/{name}.sto.gz"

# Deltas between the shipped artifacts and the metadata-derived populations, measured 2026-07-30.
# `added` rows are canonical records the shipped alignment lacks; `dropped` rows are shipped rows
# the rebuild legitimately loses. Both are re-derived per artifact in the delta tests, so these
# are tripwires: they fail when the underlying data moves, which is the point.
EXPECTED_DELTA = {
    "POLIO_unified": (106, 7),
    "NPEV_unified": (168, 0),
    "EV_unified": (272, 5),
    "PV1_unified": (715, 114),
    "PV2_unified": (356, 169),
    "PV3_unified": (261, 89),
}

# Re-measured 2026-08-14 for release 5.0.0's correctness pass. Two changes, both deliberate:
#
#   +3 dropped everywhere `FV537075`/`76`/`77` appear — carve-excluded as laboratory conversions of
#      the Mahoney parental sequence, so a shipped alignment row that the rebuild rightly loses;
#   the serotype files move in both columns because five relabels move records between PV1, PV2 and
#      PV3 (`OR208596`, `AY830709`, `HM537010`, `MG212473`, `AY297766`), which subtracts from one
#      file's `added` and adds to another's `dropped` without changing any total.
#
# `NPEV_unified` does not move: all eight affected records are poliovirus.

# Re-measured 2026-08-01 against the 4.0.0 canonical table. The three serotype files are where the
# delta moved: `dropped` went 20/23/2 to 114/169/89, and 332 of the 372 dropped rows are
# `virus_type_lost` — 2.4.1 asserted a serotype from curated data, R-TYPE-2 derives it from the
# organism name and declines where the name does not state one. The rest are 37 relabels, 3 carve
# exclusions and 2 records the partition moved out of poliovirus.

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
def populations(repository_root: Path) -> dict[str, population.AlignmentPopulation]:
    """Through `load_populations`, deliberately.

    This fixture reimplemented that function's one line for one line, which is why a dead-code sweep
    on 2026-08-14 read the function as unused and nearly deleted it. It is the only entry point the
    alignment layer offers for "every artifact's population", so the test that asserts those
    populations should be the thing that exercises it.
    """
    return population.load_populations(repository_root)


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

    Unchanged by the 4.0.0 re-anchor, and that is the point of stating it per column: this claim is
    about the evidence table and the shipped row set, neither of which moved. The *next* test, which
    goes through canonical, does move.
    """
    shipped = shipped_row_ids(repository_root, name)
    assert tier_by_column(repository_root, records, shipped, column) == {
        "backbone": backbone,
        "addon": addon,
    }


@pytest.mark.parametrize(
    ("name", "backbone", "addon"),
    [("POLIO_unified", 8732, 1251), ("NPEV_unified", 10418, 3632), ("EV_unified", 19150, 4883)],
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
    rule one record changes column — `JX181922`, whose two confidence columns disagree
    (`serotype_sequence_confident=FALSE`, `enterovirus_type_sequence_confident=TRUE`), so switching
    which column governs flips it backbone-ward. **Five** shipped rows are not in the 5.0.0 carve at
    all — the two `SEQUENCE_RESCUED_INCLUSIONS` and the three `FV5370xx` carve exclusions added on
    2026-08-14 — which is why POLIO and EV read below the shipped figures rather than one above.
    Deriving this is honest; asserting exactness on all three would assert something false.
    """
    shipped = shipped_row_ids(repository_root, name)
    counts = {"backbone": 0, "addon": 0}
    absent = 0
    for row_id in shipped:
        record = records.get(row_id)
        if record is None:
            absent += 1
            continue
        counts[record.tier] += 1
    assert absent == (5 if name in {"POLIO_unified", "EV_unified"} else 0)
    assert counts == {"backbone": backbone, "addon": addon}


def test_the_tier_difference_is_attributable_to_jx181922(
    repository_root: Path, records: dict[str, population.AlignedRecord]
) -> None:
    """Name the record, so the +1/-1 above is explained rather than merely measured."""
    shipped_polio = shipped_row_ids(repository_root, "POLIO_unified")
    movers = [
        row_id
        for row_id in shipped_polio
        if row_id in records
        and records[row_id].virus_group != contract.POLIOVIRUS
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
    """372 shipped PV rows leave. Adjudicated is not invisible: each needs a classifiable reason.

    374 until 2026-08-14, and the movement is release 5.0.0's correctness pass in one line: three
    `FV5370xx` records join `carve_excluded`, and five `serotype` relabels put five rows back in a
    serotype file they had left — so `serotype_relabelled` falls 37 -> 32 while `carve_excluded`
    rises 3 -> 6. A relabel that *returns* a row is the ledger correcting the organism name,
    which is what those five decisions are for.

    45 before the 4.0.0 re-anchor. The growth is one category: `virus_type_lost` went from 10 to
    332, because 2.4.1's `virus_type` came from curated data and R-TYPE-2 derives it from the
    organism name, declining where the name states no serotype. Those rows are still poliovirus and
    still in `POLIO_unified` and `EV_unified`; what they are not in is a serotype file, because this
    pipeline will not assert a serotype it cannot read off the deposit.
    """
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
    assert len(reasons) == 372
    assert set(reasons.values()) <= set(contract.DROP_REASONS)
    tally = {
        reason: sum(1 for v in reasons.values() if v == reason) for reason in set(reasons.values())
    }
    # Reasons are assigned most-specific first, so a record that both changed group and lost its
    # type counts once, as `group_moved`. The precedence is declared rather than incidental.
    assert tally == {
        "serotype_relabelled": 32,
        "virus_type_lost": 332,
        "group_moved": 2,
        "carve_excluded": 6,
    }
    assert sum(tally.values()) == 372
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


def test_the_family_rule_differs_from_the_baseline_only_where_the_type_column_does(
    repository_root: Path, records: dict[str, population.AlignedRecord]
) -> None:
    """Same rule, same rows, richer input — compared **per record**, which is the point.

    This compared against the shipped aggregate `families` block until 2026-08-12, asserting that
    whatever `unknown` gained the resolved families lost. That identity is nearly blind: it stayed
    green while 974 individual rows disagreed, because arrivals in one family cancelled departures
    from another. Measured now, over the 14,050 shipped `NPEV_unified` rows against 2.4.1's own
    canonical types:

    * **547** where this pipeline declines a type the baseline states — the population the deferred
      EV reference-panel pass is for. Down from 974 when R-TYPE-2 began reading the definition line.
    * **3** where this pipeline states one the baseline leaves blank: `M22129` (PV1), `M24195` (PV2)
      and `AB206350` (CVA18).
    * **zero** where both state a type and the families disagree.

    That last zero is the claim worth having, and the aggregate form could not express it.
    """
    baseline = load_baseline_canonical(repository_root)
    by_accession = {row["accession"]: row for row in baseline.values()}
    declined_here = typed_here = disagreed = 0
    for row_id in shipped_row_ids(repository_root, "NPEV_unified"):
        ours = records[row_id]
        theirs = by_accession[row_id]["virus_type"]
        if ours.family == contract.family_of(theirs):
            continue
        if not ours.virus_type:
            declined_here += 1
        elif not theirs:
            typed_here += 1
        else:
            disagreed += 1
    assert not disagreed, "a record both sides type, placed in different families"
    assert declined_here == 547
    assert typed_here == 3


# --- the blank-type sentinel ---------------------------------------------------------------------


def test_blank_types_take_the_sentinel_for_their_own_group(
    populations: dict[str, population.AlignmentPopulation],
) -> None:
    """Regression: a shared sentinel labelled 877 non-polio rows `PV?`, asserting they are polio.

    25/877 before the 4.0.0 re-anchor, 366/1,850 after, for the same reason the serotype files
    shrank: R-TYPE-2 declines a type the organism name does not state. The sentinel distinction is
    what makes that growth safe to ship — `PV?` says "poliovirus, serotype unresolved" and
    `unknown` says "not poliovirus, no type resolved", and 1,850 rows was a lot of records to
    mislabel as poliovirus by sharing one sentinel.

    1,850 -> 1,423 on 2026-08-12: R-TYPE-2 began reading the definition line, and 427 of those rows
    turned out to state their type in their own title. The sentinel population is the *residue* of a
    typing gap, so it shrinking is the gap closing.

    **`type_sort_key` is also the alignment row order** (`population.select_records`), so those 427
    records move within `NPEV_unified` and `EV_unified`. That is why the alignment rebuild covers
    all six artifacts and not the five the population arithmetic alone would imply.
    """
    polio_blanks = [r for r in populations["POLIO_unified"].records if not r.virus_type]
    npev_blanks = [r for r in populations["NPEV_unified"].records if not r.virus_type]
    assert {r.type_sort_key for r in polio_blanks} == {"PV?"}
    assert {r.type_sort_key for r in npev_blanks} == {"unknown"}
    assert len(polio_blanks) == 366
    assert len(npev_blanks) == 1423
    ev_labels = populations["EV_unified"].type_counts()
    assert ev_labels["PV?"] == 366
    assert ev_labels["unknown"] == 1423


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
