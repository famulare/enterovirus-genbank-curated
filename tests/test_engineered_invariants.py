"""Same-sequence consistency invariants for the `engineered_or_construct` column.

Two byte-identical sequences are the same genotype. `engineered` is a claim *about a genotype* —
whether someone deliberately produced it for a purpose — so two records carrying the identical
`sequence_sha256` cannot generally disagree about it.

What each check here does and does not protect, stated honestly, because an earlier version of this
file overclaimed and an adversarial review caught it:

- **Invariant A** (`test_same_sequence_patent_and_synthetic_deposits_agree`) constrains
  same-sequence `PAT`/`SYN` deposits. It is green today, and **it currently has no independent
  detection power**: every one of the 513 canonical PAT/SYN records ships TRUE, so
  `test_the_blanket_patent_flag_is_recorded_as_a_known_defect` and the SYN pins together *entail*
  that no PAT/SYN group can disagree. A exists for the state *after* the rule rewrite, when the
  population stops being uniform and the invariant starts doing work. Until then it is a
  placeholder with an exhaustive falsification control, not a live guard.

- **Invariant B** (`test_same_sequence_splits_match_the_known_defect_set`) is the live guard. It
  constrains every division, pinning the **exact set** of groups that carry a TRUE alongside a
  byte-identical FALSE. All 12 of today's violations are PAT-vs-VRL, which Invariant A's division
  restriction excludes by construction — so B, not A, is what covers the real defects.

- **The ledger check** (`test_the_ledger_does_not_split_a_byte_identical_group`) is the only check
  in this file that reads a layer this repository actually *writes*. `final/canonical/` has one
  commit in its entire history and nothing here rebuilds it, so a canonical-only check cannot see a
  curation mistake made today. The historical D2 defect was exactly that shape — a ledger assertion
  applied to one member of a byte-identical pair — and it is **still live**: the ledger sets
  `CS406482` FALSE and says nothing about `PU749297`. This check makes that visible and pins it.

Why the invariants exist at all: the D2 adjudication set `CS406482` to FALSE while leaving
`PU749297` — byte-identical, the same patent sequence re-deposited in a 2024 continuation — at TRUE.
Nothing in the suite noticed, because no check compared same-sequence records.

See `docs/engineered-full-population-readjudication.md` §7 for the measurement behind the scoping
choice, including why a sequence-length floor was rejected in favour of an explicit allowlist.

Regenerating the pins
---------------------

Every `EXPECTED_*` value and both pinned split sets are measured from the shipped release. When a
rebuild deliberately moves them, recompute rather than hand-editing:

    .venv/bin/python -m pytest tests/test_engineered_invariants.py -q

then read the actual values out of the failure messages — each assertion prints what it measured
alongside what it expected, so a diff of pin-versus-reality is legible without a separate script.
`EXPECTED_CONSTRAINED_MEMBERSHIP_SHA256` is the one exception, since a digest mismatch cannot show
its own contents; `test_invariant_a_scope_membership_is_pinned` prints the recomputed digest.

Mutation evidence
-----------------

Recorded because this repository's rule is that a check is not finished until a mutation proves it
fires (`docs/review-backlog.md`, root cause R3).

**Two rounds of this record have now been wrong, and the second failure is instructive.** Round one
named the wrong test for a mutation. Round two fixed that by transcribing `-rf` summaries verbatim —
and still misattributed mutation 6, because `-rf` names the failing *test* and never the failing
*assertion*. The swap used then (`A37539` PAT→VRL plus `AB053603`/`AB053959` VRL→PAT) was not
scope-neutral: it moved 513 → 514, so the record-count assert fired and the digest was never
reached. The method could not support the claim being made with it. Mutation 6 below is replaced
with one verified scope-neutral *and* count-neutral first, so the digest is genuinely isolated.

Nine mutations, 2026-07-30, against the design at this commit. Data mutations were applied to the
shipped artifacts themselves and reverted, with sha256 re-verified afterwards (`369b6c0b…`
canonical, `e9f0dac6…` source records, `335588b1…` ledger). Test IDs are in full; all are in this
module.

1. **`CS406436` TRUE→FALSE on disk** — the D2 defect reproduced in the shipped bytes, leaving its
   byte-identical twin `PU749305` at TRUE. **6 failed:**
   `test_the_engineered_population_matches_its_pins`,
   `test_the_blanket_patent_flag_is_recorded_as_a_known_defect`,
   `test_same_sequence_patent_and_synthetic_deposits_agree`,
   `test_invariant_a_detects_a_split_in_every_constrained_group`,
   `test_same_sequence_splits_match_the_known_defect_set`,
   `test_invariant_b_detects_a_new_split_in_every_agreeing_group`.
   The ledger check correctly does **not** fire: it measures the ledger's coherence, and this
   mutation moves canonical only. That separation is deliberate.

2. **`AB053603` FALSE→TRUE and `M14761` TRUE→FALSE on disk** — count-neutral: the TRUE total stays
   543, the ≥3000 nt count stays 58, PAT/SYN untouched, while `AB053603` now splits from its
   byte-identical twin `AB053959`. This is the mutation that left the *original* design fully green
   (`7 passed, 1 xfailed`), because a `strict=True` xfail cannot distinguish 12 violations from 13.
   **2 failed:** `test_same_sequence_splits_match_the_known_defect_set`,
   `test_invariant_b_detects_a_new_split_in_every_agreeing_group`. Verified separately that
   `test_the_engineered_population_matches_its_pins` still **passes** — detection comes from the set
   comparison, not from any count.

3. **Code sabotage: `SYN` deleted from `DELIBERATE_DEPOSIT_DIVISIONS`.** All 7 canonical SYN records
   are sha256 singletons, so a PAT-only restriction yields *identically* 178 groups / 374 records
   and both group pins stay green. **1 failed:** `test_invariant_a_scope_membership_is_pinned`
   (513 → 506). This is the only thing standing between the invariant and a silently halved scope.

4. **Code sabotage: a two-accession skip added to `disagreeing_groups`** for the real byte-identical
   PAT pair `{A37539, A37564}` — the weakening the original single-pair control passed under.
   **1 failed:** `test_invariant_a_detects_a_split_in_every_constrained_group`.

5. **Ledger mutations, both directions.** (a) An active `engineered_or_construct=TRUE` row added for
   `AB053603` while its twin `AB053959` has none → **1 failed:**
   `test_the_ledger_does_not_split_a_byte_identical_group`. (b) The existing `CS406482` D2 row
   flipped `active`→`retired`, so a *pinned* incoherence disappears → **same 1 failed.** Sensitive
   to a new curation mistake and to the quiet removal of a known one.

6. **Scope-neutral compensating swap on disk:** `A37539`/`A37564` PAT→VRL plus `M30211`/`M30212`
   VRL→PAT — both members of the leaving group, both of the joining group, all four TRUE. Verified
   before running that **every** count pin is preserved: 513 scoped, 178 groups, 374 records, 506
   PAT total, 506 PAT TRUE. **1 failed:** `test_invariant_a_scope_membership_is_pinned`, and via the
   digest this time (`a1e8c284…` → `a6ae8d40…`), which is the assertion the pin exists for.

7. **Ledger asserts TRUE for `ON596331` alone**, leaving eight byte-identical twins silent.
   **Green before this design; now 1 failed:**
   `test_the_ledger_does_not_split_a_byte_identical_group`.

8. **Ledger applies the planned flip to 7 of the 8 TRUE members of the `DD214216` group**, missing
   `LZ216101` — this repository's own landing sequence executed with one member overlooked, which is
   the D2 defect exactly. **Green before this design; now 1 failed:**
   `test_the_ledger_does_not_split_a_byte_identical_group`.

9. **`DD214217` added to `LEGITIMATE_SAME_SEQUENCE_SPLITS`, then flipped TRUE→FALSE on disk** — a
   silent resolution inside an exempt group, which the per-accession suppressor made invisible in
   both directions. **4 failed:** `test_the_engineered_population_matches_its_pins`,
   `test_the_blanket_patent_flag_is_recorded_as_a_known_defect`,
   `test_same_sequence_splits_match_the_known_defect_set`,
   `test_invariant_b_detects_a_new_split_in_every_agreeing_group`.

What no mutation reddens on its own: `test_same_sequence_patent_and_synthetic_deposits_agree`
(Invariant A) never fails without a neighbouring check failing too — the concrete form of the "no
independent detection power" caveat above. Three checks entail its green, not two: the
blanket-patent test, the SYN pins, and the membership digest. Treat A's green as uninformative
until the rule rewrite lands.
"""

from __future__ import annotations

import collections
import csv
import hashlib
from pathlib import Path

import pytest

from enterovirus_genbank_curated.contracts import ACTIVE_STATUS, read_tsv_gz

CANONICAL_METADATA = "final/canonical/sequence_metadata.tsv.gz"
SOURCE_RECORDS = "final/source/normalized_tsv/records.tsv.gz"
LEDGER = "registry/decisions.tsv"

ENGINEERED_COLUMN = "engineered_or_construct"

# Divisions whose members are deliberate deposits rather than sampled virus (Invariant A's scope).
DELIBERATE_DEPOSIT_DIVISIONS = frozenset({"PAT", "SYN"})

LONG_SEQUENCE_NT = 3000

# Invariant B escape hatch: a same-sequence split that is *legitimate*, keyed by the group's TRUE
# members (the same shape as `KNOWN_SAME_SEQUENCE_SPLITS`) with the reason it is allowed.
#
# Keyed by group rather than by accession on purpose. A per-accession suppressor let a group whose
# every TRUE member was exempt vanish from the comparison altogether, which is the F1 defect again;
# see `unexplained_true_members`. Pinning the group means an exemption records a state instead of
# hiding one.
#
# Empty today, and **empty is not the end state.** The curator's CDC-convention rule (Q6) means a
# primary named vaccine-seed deposit is TRUE while a field isolate byte-identical to it stays FALSE
# — a real distinction between a manufactured product and a virus sampled out of the world. §7 of
# the re-adjudication measures that once the Q5/Q6 vaccine-source set flips, **about 10 entries are
# required**, and **7** of those are the same groups listed in `KNOWN_SAME_SEQUENCE_SPLITS` below,
# re-disagreeing in the opposite direction: `AY082683`→(`A09260`), `AY184219`→(`DD214220`),
# `AY184220`→(`DD214222`), `AY184221`→(`DD214224`), `V01150`→(`DD214219`…), `X00595`→(`DD214221`),
# `X00596`→(`DD214223`). So entries migrate from that pin into this one; they do not simply
# disappear. (Said 6 previously — that figure was §7's full-length/short split, a different
# partition.)
LEGITIMATE_SAME_SEQUENCE_SPLITS: dict[tuple[str, ...], str] = {}

# Population pins for the column itself. Nothing anywhere pinned these before, which is precisely
# how the values drifted far enough to need a full re-adjudication: 543 records shipped TRUE and no
# check knew what the number was supposed to be.
#
# `EXPECTED_PAT_TRUE == EXPECTED_PAT_IN_CANONICAL` is not a curation outcome. It is the signature of
# the defect: `\bPAT\b` matched as free text inside a 20-field blob, so *every* patent-division
# record is flagged engineered regardless of what its sequence is. When the rule is rewritten this
# equality is the first thing that should break.
EXPECTED_TRUE_TOTAL = 543
EXPECTED_TRUE_AT_LEAST_3000NT = 58
EXPECTED_PAT_IN_CANONICAL = 506
EXPECTED_PAT_TRUE = 506
EXPECTED_SYN_IN_CANONICAL = 7
EXPECTED_SYN_TRUE = 7

# Invariant A's scope, pinned as a record count rather than only as constrained-group counts.
# Without this, deleting `SYN` from `DELIBERATE_DEPOSIT_DIVISIONS` is undetectable: all 7 canonical
# SYN records are sha256 singletons, so they contribute nothing to the group/record pins below and
# a PAT-only restriction yields *identically* 178/374.
EXPECTED_SCOPED_RECORDS = 513

# Pinned so a future change that *stops* constraining records — by moving them out of PAT/SYN, or
# by dropping them from canonical — fails loudly instead of turning the invariant into a check over
# an empty set.
EXPECTED_CONSTRAINED_GROUPS = 178
EXPECTED_CONSTRAINED_RECORDS = 374

# Counts alone constrain cardinality, not membership: a compensating swap (one group leaving the
# scope, another joining) preserves 178/374 exactly. This digest pins *which* groups and which
# accessions, so such a swap is visible.
EXPECTED_CONSTRAINED_MEMBERSHIP_SHA256 = (
    "a1e8c284da03e2309f28f00de24e3942b4374e2d943da31220abe399706ed439"
)

# The population the general falsification controls run over.
#
# Moved at the 2.1.5 → 2.3.0 release refresh: 1644 → 1625 and 1632 → 1613. That release drops 245
# canonical records (unaligned non-polio), which collapses 19 identical-sequence groups below two
# members. Both counts fall by exactly 19 because all 19 were agreeing groups. Purely a
# population-size effect — re-measured, not derived.
EXPECTED_MULTI_MEMBER_GROUPS = 1625
EXPECTED_AGREEING_MULTI_MEMBER_GROUPS = 1613

# Invariant B's outstanding violations, pinned as the exact set of TRUE members per group.
#
# A count would pass with the wrong rows, and a `strict=True` xfail — what this file used before —
# has only two states and so cannot distinguish 12 violations from 13. A *new* same-sequence split,
# which is the defect class this file exists to prevent, was therefore invisible. Set equality
# catches a new violation and a silent resolution alike.
#
# Every entry resolves when the re-adjudication's flips reach `final/canonical/`. That needs the
# private pipeline to rebuild and re-ship; nothing in this repository writes that file. When the
# rebuild lands, this pin goes to `{}` minus whatever moves into
# `LEGITIMATE_SAME_SEQUENCE_SPLITS` above.
#
# `EXPECTED_KNOWN_SPLIT_COUNT` is asserted separately so that moving a group from this pin into the
# legitimate one cannot happen silently: the union assertion alone is satisfied by any partition of
# the same 12 groups, including emptying this set wholesale.
KNOWN_SAME_SEQUENCE_SPLITS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("A09260",),
        (
            "DD214216",
            "DI499146",
            "FV537074",
            "HC025129",
            "HV932178",
            "JC013103",
            "LY501106",
            "LZ216101",
        ),
        ("DD214217",),
        ("DD214218",),
        ("DD214219", "DI499147", "HV202313", "JC013104"),
        ("DD214220",),
        ("DD214221",),
        ("DD214222",),
        ("DD214223",),
        ("DD214224",),
        ("HW349523", "LP131905", "MA783942", "MP510547"),
        ("PE314016", "PH149759"),
    }
)

EXPECTED_KNOWN_SPLIT_COUNT = 12

# Byte-identical groups where the ledger's own assertions are partial: it speaks for some members
# and either contradicts, or stays silent about, byte-identical siblings that ship a different
# value. Keyed by the asserted accessions.
#
# The first three are the live D2 defect. `CS406483` additionally carries the *wrong* value — the
# re-adjudication found that pair genuinely engineered (a unique AgeI site), so its active FALSE row
# needs correcting rather than extending to its twin.
#
# `DD214221` is a fourth instance nobody had recorded, and it was invisible to the differential
# formulation this check replaced: an active TRUE assertion whose byte-identical twin `X00595`
# (Sabin 2, shipping FALSE) has no row at all. Same defect shape as D2 with the polarity reversed.
KNOWN_LEDGER_INCOHERENT_GROUPS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("CS406436",),
        ("CS406482",),
        ("CS406483",),
        ("DD214221",),
    }
)


@pytest.fixture(scope="module")
def canonical(repository_root: Path) -> dict[str, dict[str, str]]:
    """One read of the shipped canonical table, keyed by accession."""
    header, rows = read_tsv_gz(repository_root / CANONICAL_METADATA)
    index = {name: position for position, name in enumerate(header)}
    wanted = ("accession", ENGINEERED_COLUMN, "sequence_sha256", "sequence_length_nt")
    return {row[index["accession"]]: {name: row[index[name]] for name in wanted} for row in rows}


@pytest.fixture(scope="module")
def engineered_by_accession(canonical: dict[str, dict[str, str]]) -> dict[str, str]:
    return {accession: row[ENGINEERED_COLUMN] for accession, row in canonical.items()}


@pytest.fixture(scope="module")
def sha256_by_accession(canonical: dict[str, dict[str, str]]) -> dict[str, str]:
    return {accession: row["sequence_sha256"] for accession, row in canonical.items()}


@pytest.fixture(scope="module")
def length_by_accession(canonical: dict[str, dict[str, str]]) -> dict[str, int]:
    return {accession: int(row["sequence_length_nt"]) for accession, row in canonical.items()}


@pytest.fixture(scope="module")
def division_by_accession(repository_root: Path) -> dict[str, str]:
    header, rows = read_tsv_gz(repository_root / SOURCE_RECORDS)
    index = {name: position for position, name in enumerate(header)}
    return {row[index["accession"]]: row[index["division"]] for row in rows}


@pytest.fixture(scope="module")
def active_engineered_ledger_values(repository_root: Path) -> dict[str, str]:
    """Active ledger assertions about `engineered_or_construct`, keyed by accession."""
    with (repository_root / LEDGER).open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_MINIMAL))
    return {
        row["accession"]: row["new_value"].strip().upper()
        for row in rows
        if row["field_name"] == ENGINEERED_COLUMN and row["status"] == ACTIVE_STATUS
    }


def group_by_sequence(
    engineered: dict[str, str],
    sha256: dict[str, str],
    division: dict[str, str],
    *,
    restrict_to_divisions: frozenset[str] | None = None,
) -> dict[str, list[tuple[str, str]]]:
    """Bucket accessions by `sequence_sha256`, carrying each one's engineered value.

    `restrict_to_divisions` narrows the population to records whose *source* division is in the
    given set, which is what scopes Invariant A.
    """
    groups: dict[str, list[tuple[str, str]]] = collections.defaultdict(list)
    for accession, value in engineered.items():
        keep = restrict_to_divisions is None or division.get(accession) in restrict_to_divisions
        if not keep:
            continue
        groups[sha256[accession]].append((accession, value))
    return dict(groups)


def disagreeing_groups(
    groups: dict[str, list[tuple[str, str]]],
) -> dict[str, list[tuple[str, str]]]:
    return {
        digest: sorted(members)
        for digest, members in groups.items()
        if len({value for _, value in members}) > 1
    }


def unexplained_true_members(
    groups: dict[str, list[tuple[str, str]]],
) -> frozenset[tuple[str, ...]]:
    """The TRUE members of every group that splits TRUE/FALSE.

    Keyed by accession tuple rather than digest: an accession belongs to exactly one sha256 group,
    so the tuples are disjoint, and a diff of two of these sets names records rather than hashes.

    **No exemption filtering happens here, deliberately.** An earlier version subtracted exempt
    members before building the tuple and dropped the group entirely when the result was empty. That
    reintroduced the F1 defect this file exists to close: with every TRUE member of a group exempt,
    the group became invisible in *both* directions, so a silent resolution inside it produced no
    red. Demonstrated by exempting `DD214217` and then flipping it FALSE — identical offender set,
    suite green. It was masked only by the blanket-patent test, which is scheduled for deletion in
    the same change that populates the allowlist.

    So exemptions do not suppress; they are pinned separately in `LEGITIMATE_SAME_SEQUENCE_SPLITS`
    and the caller asserts against the union. A split always registers; what changes is which pinned
    bucket it belongs to.
    """
    return frozenset(
        tuple(sorted(accession for accession, value in members if value == "TRUE"))
        for members in groups.values()
        if {value for _, value in members} == {"TRUE", "FALSE"}
    )


def accessions_by_sha256(
    engineered: dict[str, str],
    sha256: dict[str, str],
) -> dict[str, list[str]]:
    """Bucket accessions by sequence digest. Split out so callers can build it once.

    The exhaustive ledger control evaluates one plant per member per group; rebuilding this index
    inside the check made that quadratic and took 89 s. Hoisted, the same coverage runs in ~4 s.
    """
    by_digest: dict[str, list[str]] = collections.defaultdict(list)
    for accession in engineered:
        by_digest[sha256[accession]].append(accession)
    return by_digest


def ledger_incoherent_groups(
    engineered: dict[str, str],
    ledger: dict[str, str],
    by_digest: dict[str, list[str]],
) -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """Byte-identical groups where the ledger's assertions are partial or self-contradictory.

    Returns digest -> (asserted accessions, silent accessions whose canonical value disagrees).

    This replaces a differential formulation that computed canonical disagreements before and after
    applying the ledger and kept only groups whose digest was *new*. That filter made the check
    blind inside the 12 groups canonical already splits — 280 records, and precisely the
    `DD2142xx`/`A09260`/`PE314016` population the re-adjudication is about. Two demonstrations, both
    of which left the module fully green: asserting TRUE for `ON596331` alone while eight
    byte-identical twins stayed silent, and applying the planned flip to 7 of the 8 TRUE members of
    the `DD214216` group. The second is this repository's own landing sequence executed with one
    member missed — the D2 defect, in the D2 shape, invisible to the check named after it.

    The rule here needs no baseline subtraction: within one byte-identical group, curation must
    either speak for the whole group or agree with what the rest already ships. Two ways to break
    that, both caught:

    - **contradictory** — the ledger asserts more than one distinct value inside the group;
    - **partial** — the ledger asserts one value and a member it is silent about ships a different
      one, so applying the ledger would leave the group inconsistent.
    """
    incoherent: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    for digest, members in by_digest.items():
        asserted = {a: ledger[a] for a in members if a in ledger}
        if not asserted:
            continue
        values = set(asserted.values())
        silent = [a for a in members if a not in ledger]
        contradictory = len(values) > 1
        partial = len(values) == 1 and any(engineered[a] != next(iter(values)) for a in silent)
        if contradictory or partial:
            # `contradictory or ...` short-circuited to True here, so every silent member was
            # reported as disagreeing even when it agreed with one of the asserted values. The bare
            # membership test is already correct for both branches.
            disagreeing = tuple(sorted(a for a in silent if engineered[a] not in values))
            incoherent[digest] = (tuple(sorted(asserted)), disagreeing)
    return incoherent


def flip_one_member_per_group(
    engineered: dict[str, str],
    groups: dict[str, list[tuple[str, str]]],
) -> tuple[dict[str, str], dict[str, str]]:
    """Mutate one member of every supplied group at once, and report which.

    sha256 groups partition the records, so flipping one member of each cannot interfere across
    groups — which is what lets a single call to the real check cover every group at once instead
    of hand-picking one pair to represent them all.
    """
    mutated = dict(engineered)
    flipped: dict[str, str] = {}
    for digest, members in groups.items():
        accession, value = sorted(members)[0]
        mutated[accession] = "FALSE" if value == "TRUE" else "TRUE"
        flipped[digest] = accession
    return mutated, flipped


def test_the_engineered_column_is_a_clean_boolean(engineered_by_accession: dict[str, str]) -> None:
    """A disagreement check is meaningless if the column carries blanks or free text."""
    values = set(engineered_by_accession.values())
    assert values == {"TRUE", "FALSE"}, f"unexpected {ENGINEERED_COLUMN} values: {sorted(values)}"


def test_every_canonical_record_resolves_to_a_source_division(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant A's scoping depends on this join being total.

    `group_by_sequence` uses `division.get(accession)`, which yields `None` for a missing accession
    and silently drops it from the PAT/SYN population. If canonical ever carried a record absent
    from the source records table, Invariant A would stop constraining it without any test
    noticing. Assert the join is total so that failure mode cannot arise quietly.
    """
    unresolved = sorted(a for a in engineered_by_accession if a not in division_by_accession)
    assert unresolved == [], (
        f"{len(unresolved)} canonical accessions have no source-layer division, so Invariant A "
        f"silently excludes them: {unresolved[:10]}"
    )


def test_the_engineered_population_matches_its_pins(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
    length_by_accession: dict[str, int],
) -> None:
    """Drift detector for the counts that moved silently and forced the re-adjudication.

    A change here is not necessarily a defect — the planned rule rewrite is expected to move every
    one of these numbers. It has to be *deliberate*, which means updating the pin and the
    disposition tables in `docs/engineered-full-population-readjudication.md` together.
    """
    true_accessions = {a for a, v in engineered_by_accession.items() if v == "TRUE"}
    assert len(true_accessions) == EXPECTED_TRUE_TOTAL, (
        f"{len(true_accessions)} records ship {ENGINEERED_COLUMN}=TRUE, pinned at "
        f"{EXPECTED_TRUE_TOTAL}"
    )

    long_true = {a for a in true_accessions if length_by_accession[a] >= LONG_SEQUENCE_NT}
    assert len(long_true) == EXPECTED_TRUE_AT_LEAST_3000NT, (
        f"{len(long_true)} records ship TRUE at >={LONG_SEQUENCE_NT} nt, pinned at "
        f"{EXPECTED_TRUE_AT_LEAST_3000NT}. This is the hand-adjudicated population; if it changed, "
        f"the disposition table in the re-adjudication doc is now incomplete."
    )

    for division, expected_total, expected_true in (
        ("PAT", EXPECTED_PAT_IN_CANONICAL, EXPECTED_PAT_TRUE),
        ("SYN", EXPECTED_SYN_IN_CANONICAL, EXPECTED_SYN_TRUE),
    ):
        members = {a for a in engineered_by_accession if division_by_accession.get(a) == division}
        flagged = members & true_accessions
        assert len(members) == expected_total, (
            f"{len(members)} canonical records are division {division}, pinned at {expected_total}"
        )
        assert len(flagged) == expected_true, (
            f"{len(flagged)} of {len(members)} {division} records ship TRUE, pinned at "
            f"{expected_true}"
        )


def test_the_blanket_patent_flag_is_recorded_as_a_known_defect(
    engineered_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Every single patent-division record ships TRUE, and that is the bug, not a finding.

    Asserted rather than merely documented so the situation cannot be quietly *partially* fixed:
    flipping some patent records without rewriting the predicate would leave a half-migrated column
    that reads as if it had been adjudicated. When the rule rewrite lands this test must be deleted
    along with the pins above, deliberately.
    """
    patent = {a for a in engineered_by_accession if division_by_accession.get(a) == "PAT"}
    flagged = {a for a in patent if engineered_by_accession[a] == "TRUE"}
    assert flagged == patent, (
        "some patent records now ship FALSE, so the blanket flag is partially corrected: "
        f"{len(patent) - len(flagged)} of {len(patent)}. Finish the predicate rewrite and retire "
        "this test rather than leaving the column half-adjudicated."
    )


def test_invariant_a_scope_membership_is_pinned(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Pin *which* records Invariant A constrains, not merely how many.

    The scoped record count is pinned separately from the constrained-group counts because the two
    fail to different mutations: dropping `SYN` from the division set moves 513 and leaves 178/374
    untouched, while a compensating scope swap moves the digest and leaves all three counts intact.
    """
    scoped = [
        a
        for a in engineered_by_accession
        if division_by_accession.get(a) in DELIBERATE_DEPOSIT_DIVISIONS
    ]
    assert len(scoped) == EXPECTED_SCOPED_RECORDS, (
        f"Invariant A's scope holds {len(scoped)} records, pinned at {EXPECTED_SCOPED_RECORDS}. "
        f"A drop here means a division left {sorted(DELIBERATE_DEPOSIT_DIVISIONS)} without the "
        f"group counts noticing."
    )

    groups = group_by_sequence(
        engineered_by_accession,
        sha256_by_accession,
        division_by_accession,
        restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
    )
    constrained = {
        digest: sorted(a for a, _ in members)
        for digest, members in groups.items()
        if len(members) > 1
    }
    payload = "\n".join(
        f"{digest}\t{','.join(members)}" for digest, members in sorted(constrained.items())
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    assert digest == EXPECTED_CONSTRAINED_MEMBERSHIP_SHA256, (
        f"Invariant A's constrained membership digest is {digest}, pinned at "
        f"{EXPECTED_CONSTRAINED_MEMBERSHIP_SHA256}. {len(constrained)} groups / "
        f"{sum(len(m) for m in constrained.values())} records. If the change is intended, replace "
        f"the pin with the value printed here."
    )


def test_same_sequence_patent_and_synthetic_deposits_agree(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant A. Unconditional: no allowlist, no length floor.

    Green today for a reason that is not a curation outcome: all 513 scoped records ship TRUE, so
    uniformity — not consistent adjudication — is what makes this pass. See the module docstring.
    """
    groups = group_by_sequence(
        engineered_by_accession,
        sha256_by_accession,
        division_by_accession,
        restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
    )
    constrained = {digest: members for digest, members in groups.items() if len(members) > 1}

    assert len(constrained) == EXPECTED_CONSTRAINED_GROUPS, (
        f"Invariant A now constrains {len(constrained)} sha256 groups, not "
        f"{EXPECTED_CONSTRAINED_GROUPS}. If that is intended, update the pin; if it dropped, the "
        f"invariant may have stopped covering the records it exists to cover."
    )
    assert sum(len(m) for m in constrained.values()) == EXPECTED_CONSTRAINED_RECORDS

    failures = disagreeing_groups(constrained)
    assert failures == {}, (
        "byte-identical patent/synthetic deposits disagree on "
        f"{ENGINEERED_COLUMN}: {failures}. Two deposits of the same bytes are the same genotype; "
        "adjudicate the group, not one member of it."
    )


def test_invariant_a_detects_a_split_in_every_constrained_group(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Falsification control for Invariant A, exhaustive rather than by example.

    An earlier version planted the defect in one hand-picked pair. That let the guard be weakened
    for any *other* group — a two-accession skip inside `disagreeing_groups` — while the control
    still passed. Flipping one member of all 178 groups at once and requiring all 178 to be named
    closes that: a skip targeting any group fails here, and there is no hardcoded accession left to
    raise `KeyError` if a record leaves canonical.
    """
    groups = group_by_sequence(
        engineered_by_accession,
        sha256_by_accession,
        division_by_accession,
        restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
    )
    constrained = {digest: members for digest, members in groups.items() if len(members) > 1}
    mutated, flipped = flip_one_member_per_group(engineered_by_accession, constrained)

    detected = disagreeing_groups(
        group_by_sequence(
            mutated,
            sha256_by_accession,
            division_by_accession,
            restrict_to_divisions=DELIBERATE_DEPOSIT_DIVISIONS,
        )
    )
    missed = sorted(flipped[digest] for digest in constrained if digest not in detected)
    assert missed == [], (
        f"Invariant A failed to detect a planted split in {len(missed)} of {len(constrained)} "
        f"constrained groups: {missed[:10]}. The guard does not cover the scope it claims to."
    )


def test_same_sequence_splits_match_the_known_defect_set(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Invariant B. The outstanding split set must be exactly what is pinned.

    Both directions are failures worth a red. A group appearing means a *new* same-sequence split —
    the defect class this file exists to prevent. A group disappearing means the rebuild landed, or
    something silently changed a value, and the pin plus the disposition tables need updating
    together.
    """
    overlap = KNOWN_SAME_SEQUENCE_SPLITS & frozenset(LEGITIMATE_SAME_SEQUENCE_SPLITS)
    assert overlap == frozenset(), (
        f"a group is pinned as both a known defect and a legitimate split: {sorted(overlap)}. "
        f"It is one or the other."
    )
    assert len(KNOWN_SAME_SEQUENCE_SPLITS) == EXPECTED_KNOWN_SPLIT_COUNT, (
        f"{len(KNOWN_SAME_SEQUENCE_SPLITS)} groups are pinned as known defects, expected "
        f"{EXPECTED_KNOWN_SPLIT_COUNT}. Asserted separately from the union below because the union "
        f"is satisfied by *any* partition of the same groups — including moving every known defect "
        f"into the legitimate allowlist, which would silently retire the whole invariant."
    )

    groups = group_by_sequence(engineered_by_accession, sha256_by_accession, division_by_accession)
    offenders = unexplained_true_members(groups)
    expected = KNOWN_SAME_SEQUENCE_SPLITS | frozenset(LEGITIMATE_SAME_SEQUENCE_SPLITS)

    appeared = sorted(offenders - expected)
    resolved = sorted(expected - offenders)
    assert offenders == expected, (
        f"the same-sequence split set moved. NEW (a TRUE now sits beside a byte-identical FALSE "
        f"and is in neither pinned bucket): {appeared}. RESOLVED (pinned but no longer splitting): "
        f"{resolved}. A new group is a defect; a resolved group means the pin, "
        f"LEGITIMATE_SAME_SEQUENCE_SPLITS and the re-adjudication doc need updating together. "
        f"Moving a group from the known-defect pin to the legitimate one is how a reviewed "
        f"exemption lands — it must never simply disappear from both, and the count assertion "
        f"above is what makes the move visible."
    )


def test_invariant_b_detects_a_new_split_in_every_agreeing_group(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    division_by_accession: dict[str, str],
) -> None:
    """Falsification control for Invariant B, over every group it could possibly protect.

    This is the check the previous `strict=True` xfail could not perform. An xfail is binary: it
    fails while any violation exists, so a thirteenth one is indistinguishable from the twelve
    already there. Demonstrated at the time with a count-neutral mutation that left the suite fully
    green. Here every currently-agreeing multi-member group is split at once and each must surface.
    """
    groups = group_by_sequence(engineered_by_accession, sha256_by_accession, division_by_accession)
    multi = {digest: members for digest, members in groups.items() if len(members) > 1}
    assert len(multi) == EXPECTED_MULTI_MEMBER_GROUPS, (
        f"{len(multi)} multi-member sha256 groups, pinned at {EXPECTED_MULTI_MEMBER_GROUPS}"
    )

    agreeing = {
        digest: members
        for digest, members in multi.items()
        if len({value for _, value in members}) == 1
    }
    assert len(agreeing) == EXPECTED_AGREEING_MULTI_MEMBER_GROUPS, (
        f"{len(agreeing)} multi-member groups currently agree, pinned at "
        f"{EXPECTED_AGREEING_MULTI_MEMBER_GROUPS}"
    )

    mutated, flipped = flip_one_member_per_group(engineered_by_accession, agreeing)
    offenders = unexplained_true_members(
        group_by_sequence(mutated, sha256_by_accession, division_by_accession)
    )
    flagged = {accession for group in offenders for accession in group}

    missed = sorted(
        digest
        for digest, members in agreeing.items()
        if not any(accession in flagged for accession, _ in members)
    )
    assert missed == [], (
        f"Invariant B failed to detect a planted split in {len(missed)} of {len(agreeing)} "
        f"agreeing groups: {[flipped[d] for d in missed[:10]]}. A new same-sequence split would "
        f"ship unnoticed."
    )


def test_every_engineered_ledger_subject_is_in_canonical(
    engineered_by_accession: dict[str, str],
    active_engineered_ledger_values: dict[str, str],
) -> None:
    """The mirror of the source-division join check, on the ledger side.

    `ledger_incoherent_groups` indexes groups from canonical, so an active assertion about an
    accession *absent* from canonical is silently skipped — the same `.get()`-shaped hole that
    `test_every_canonical_record_resolves_to_a_source_division` exists to prevent in the other
    direction. It matters because the ledger already carries 176 active rows for accessions outside
    canonical (membership exclusions, carve exclusions, serotype confirmations), 10 of whose
    subjects are byte-identical to records that *are* in canonical.

    Today no `engineered_or_construct` row is in that state, and this pins it. Q5's planned
    carve-exclusion of `FV537075`–`FV537077` moves records out of canonical, so this is the
    assertion that will fire if an engineered assertion is ever left pointing at one of them.
    """
    orphaned = sorted(
        a for a in active_engineered_ledger_values if a not in engineered_by_accession
    )
    assert orphaned == [], (
        f"{len(orphaned)} active {ENGINEERED_COLUMN} ledger rows name accessions absent from "
        f"canonical, so the ledger-coherence check silently ignores them: {orphaned[:10]}. Either "
        f"the row is stale, or the record left canonical and its assertion needs retiring with it."
    )


def test_the_ledger_does_not_split_a_byte_identical_group(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    active_engineered_ledger_values: dict[str, str],
) -> None:
    """Curation must not assert a value for part of a byte-identical group.

    This is the only check here with real detection power over work done *today*. It reads
    `registry/decisions.tsv`, which this repository writes, rather than `final/canonical/`, which
    it does not — `git log -- final/canonical` has exactly one commit, the initial release.

    Compares group *content*, not a before/after digest diff. See `ledger_incoherent_groups` for why
    the differential version was blind across 280 records, including the population this whole
    re-adjudication concerns.
    """
    incoherent = ledger_incoherent_groups(
        engineered_by_accession,
        active_engineered_ledger_values,
        accessions_by_sha256(engineered_by_accession, sha256_by_accession),
    )
    found = frozenset(asserted for asserted, _ in incoherent.values())

    appeared = sorted(found - KNOWN_LEDGER_INCOHERENT_GROUPS)
    resolved = sorted(KNOWN_LEDGER_INCOHERENT_GROUPS - found)
    detail = {
        ",".join(asserted): list(silent)
        for asserted, silent in incoherent.values()
        if asserted in set(appeared)
    }
    assert found == KNOWN_LEDGER_INCOHERENT_GROUPS, (
        f"the set of byte-identical groups the ledger speaks for only partially moved. NEW: "
        f"{appeared} (silent-but-disagreeing siblings: {detail}). RESOLVED: {resolved}. A new "
        f"entry means a decision was recorded for some members of a byte-identical group and not "
        f"the rest — the D2 defect, repeated. Adjudicate the group, not one member of it."
    )


def test_the_ledger_split_check_detects_a_partial_assertion_in_every_group(
    engineered_by_accession: dict[str, str],
    sha256_by_accession: dict[str, str],
    active_engineered_ledger_values: dict[str, str],
) -> None:
    """Falsification control for the ledger check, over **every** multi-member group.

    Deliberately not restricted to currently-agreeing groups. An earlier version was, and that is
    how the differential formulation's blind spot survived review: a control whose population is
    drawn from the region where the guard already works cannot falsify the guard's coverage. The
    groups canonical already splits are exactly where the old check saw nothing, so they are exactly
    what this must cover.

    **Every silent member is used as the disagreeing one, not just the first.** Widening the
    population was not enough: an earlier version always planted the opposite of
    `engineered[members[1]]`, and `members[1]` is always the alphabetically-first silent member, so
    a guard inspecting only one silent member was indistinguishable from one inspecting all.
    Verified by sabotage: restricting `partial` to `sorted(silent)[:1]` left the module green.

    **The contradictory branch gets its own plant.** The partial plant pops every sibling row, which
    forces `len(values) == 1` and so can never reach that branch; disabling `contradictory`
    entirely was invisible to the suite.
    """
    by_digest = accessions_by_sha256(engineered_by_accession, sha256_by_accession)
    multi = {d: sorted(m) for d, m in by_digest.items() if len(m) > 1}
    assert len(multi) == EXPECTED_MULTI_MEMBER_GROUPS

    missed_partial: list[str] = []
    missed_contradictory: list[str] = []
    for digest, members in multi.items():
        # PARTIAL: for each member in turn, assert the opposite of what *that* member ships and
        # leave the rest silent. Iterating over every member means a guard that only ever looks at
        # one silent sibling fails here.
        for disagreeing_with in members:
            planted = dict(active_engineered_ledger_values)
            for other in members:
                planted.pop(other, None)
            target = next(m for m in members if m != disagreeing_with)
            planted[target] = (
                "FALSE" if engineered_by_accession[disagreeing_with] == "TRUE" else "TRUE"
            )
            if digest not in ledger_incoherent_groups(engineered_by_accession, planted, by_digest):
                missed_partial.append(f"{target} vs silent {disagreeing_with} ({digest[:12]})")

        # CONTRADICTORY: two members asserted with opposite values. Unreachable by the plant above,
        # because that one leaves exactly one asserted value in the group.
        planted = dict(active_engineered_ledger_values)
        planted[members[0]] = "TRUE"
        planted[members[1]] = "FALSE"
        if digest not in ledger_incoherent_groups(engineered_by_accession, planted, by_digest):
            missed_contradictory.append(f"{members[0]}/{members[1]} ({digest[:12]})")

    assert missed_partial == [], (
        f"the ledger check missed a planted *partial* assertion in {len(missed_partial)} cases "
        f"across {len(multi)} byte-identical groups: {missed_partial[:10]}. Those groups are "
        f"unguarded against the D2 defect."
    )
    assert missed_contradictory == [], (
        f"the ledger check missed a planted *contradictory* pair in "
        f"{len(missed_contradictory)} of {len(multi)} byte-identical groups: "
        f"{missed_contradictory[:10]}. Two active rows asserting opposite values about the same "
        f"genotype would ship unnoticed."
    )
