"""Correctness checks for the divergence metric and the coordinate frames.

Run with `uv run site/pipeline/cli.py selftest`. These are the checks that bite —
each one fails loudly if a genuine mistake is made, rather than confirming that the
code does whatever it currently does.

Kept here rather than under the repository's `tests/` because this pipeline is a
standalone script directory, not part of the installed package, and it must stay
runnable from a fresh clone with nothing but `uv`.
"""

from __future__ import annotations

import numpy as np

import contract
import divergence
import frame
import reference

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if condition:
        print(f"  ok    {message}")
    else:
        print(f"  FAIL  {message}")
        FAILURES.append(message)


def check_equal(actual, expected, message: str) -> None:
    check(actual == expected, f"{message} (got {actual!r}, expected {expected!r})")


# --- Synthetic metric cases ------------------------------------------------


def _alignment(rows: dict[str, str]) -> frame.Alignment:
    """Build an Alignment from plain strings, for hand-checkable cases."""
    ids = list(rows)
    width = len(rows[ids[0]])
    raw = np.frombuffer("".join(rows[i] for i in ids).encode("ascii"), dtype=np.uint8)
    matrix = frame._LOOKUP[raw].reshape(len(ids), width)
    return frame.Alignment(
        name="synthetic",
        ids=ids,
        index={acc: i for i, acc in enumerate(ids)},
        matrix=matrix,
        rf="",
        provenance={},
    )


def _measure_pair(ref_seq: str, query: str) -> dict:
    align = _alignment({"REF": ref_seq, "Q": query})
    columns = np.arange(len(ref_seq), dtype=np.int64)
    refs = reference.References(
        sequences=align.matrix[[0]][:, columns],
        row_index=np.array([0], dtype=np.int32),
        kinds=[reference.KIND_SABIN],
        labels=["synthetic"],
    )
    counts = divergence.measure(align, np.array([1]), columns, refs)
    return {key: value[0] for key, value in counts.items()}


def synthetic_cases() -> None:
    print("\nsynthetic metric cases")

    identical = _measure_pair("ATGAAAGGGCCCTTT", "ATGAAAGGGCCCTTT")
    check_equal(int(identical["comparable"]), 5, "identical: all five codons comparable")
    check_equal(int(identical["synonymous"]), 0, "identical: no synonymous difference")
    check_equal(int(identical["nonsynonymous"]), 0, "identical: no non-synonymous difference")

    # AAA->AAG is Lys->Lys; GGG->GAG is Gly->Glu.
    substituted = _measure_pair("ATGAAAGGGCCCTTT", "ATGAAGGAGCCCTTT")
    check_equal(int(substituted["comparable"]), 5, "substitutions: five codons comparable")
    check_equal(int(substituted["synonymous"]), 1, "AAA->AAG counts one synonymous")
    check_equal(int(substituted["nonsynonymous"]), 1, "GGG->GAG counts one non-synonymous")

    # Two positions differ in one codon: still one event, classified by its protein
    # outcome. GGG->GAA is Gly->Glu.
    multi = _measure_pair("ATGGGGTTT", "ATGGAATTT")
    check_equal(int(multi["nonsynonymous"]), 1, "two changed positions in one codon count once")

    # An in-frame three-base deletion: one indel event, no frameshift.
    in_frame = _measure_pair("ATGAAAGGGCCCTTT", "ATGAAA---CCCTTT")
    check_equal(int(in_frame["comparable"]), 4, "in-frame deletion: deleted codon not comparable")
    check_equal(int(in_frame["indel_events"]), 1, "in-frame deletion is one indel event")
    check_equal(int(in_frame["indel_codons"]), 1, "in-frame deletion affects one codon")
    check_equal(int(in_frame["assessable"]), 5, "the deleted codon is assessable, not comparable")
    check_equal(int(in_frame["nonsynonymous"]), 1, "in-frame deletion scores non-synonymous")
    check(not bool(in_frame["frameshift"]), "in-frame deletion sets no frameshift flag")

    # A single-base deletion shifts the frame.
    shifted = _measure_pair("ATGAAAGGGCCCTTT", "ATGAA-GGGCCCTTT")
    check_equal(int(shifted["indel_events"]), 1, "one-base deletion is one indel event")
    check(bool(shifted["frameshift"]), "one-base deletion sets the frameshift flag")

    # Two separate runs are two events even though both are three bases long.
    two_runs = _measure_pair("ATGAAAGGGCCCTTT", "ATG---GGG---TTT")
    check_equal(int(two_runs["indel_events"]), 2, "two separated deletions are two events")
    check_equal(int(two_runs["indel_codons"]), 2, "two separated deletions affect two codons")
    check_equal(int(two_runs["nonsynonymous"]), 2, "each affected codon scores once")

    # A long deletion is charged per codon it touches, not once and not per base.
    long_gap = _measure_pair("ATGAAAGGGCCCTTT", "ATG---------TTT")
    check_equal(int(long_gap["indel_events"]), 1, "a nine-base deletion is one event")
    check_equal(int(long_gap["indel_codons"]), 3, "a nine-base deletion affects three codons")
    check_equal(int(long_gap["comparable"]), 2, "only the flanking codons stay comparable")
    check_equal(int(long_gap["assessable"]), 5, "assessable spans comparable plus indel codons")

    # Leading and trailing absence is missing data, not deletion.
    tails = _measure_pair("ATGAAAGGGCCCTTT", "---AAAGGGCCC---")
    check_equal(int(tails["comparable"]), 3, "tails reduce the comparable count")
    check_equal(int(tails["assessable"]), 3, "tails are outside the assessable span")
    check_equal(int(tails["indel_events"]), 0, "tails are not indel events")
    check_equal(int(tails["nonsynonymous"]), 0, "tails contribute no difference")

    # An ambiguity code is not covered: it lowers the denominator, never the numerator.
    ambiguous = _measure_pair("ATGAAAGGGCCCTTT", "ATGAANGGGCCCTTT")
    check_equal(int(ambiguous["comparable"]), 4, "N reduces the comparable count")
    check_equal(int(ambiguous["synonymous"]), 0, "N contributes no synonymous difference")
    check_equal(
        int(ambiguous["nonsynonymous"]), 0, "N contributes no non-synonymous difference"
    )
    # The distinction that makes the above work: an ambiguity code is material, a
    # gap is not, so only the gap can be an indel.
    check_equal(int(ambiguous["indel_events"]), 0, "N is not an indel event")
    check(not bool(ambiguous["frameshift"]), "N raises no frameshift flag")
    run_of_n = _measure_pair("ATGAAAGGGCCCTTT", "ATGNNNGGGCCCTTT")
    check_equal(int(run_of_n["indel_events"]), 0, "a run of N is not an indel event")
    check_equal(int(run_of_n["comparable"]), 4, "a run of N costs exactly its codon")
    check_equal(int(run_of_n["assessable"]), 4, "a run of N is not assessable either")

    # An insertion relative to the reference, inside the covered span.
    insertion = _measure_pair("ATGAAA---CCCTTT", "ATGAAAGGGCCCTTT")
    check_equal(int(insertion["indel_events"]), 1, "insertion relative to reference is one event")

    # U notation must fold onto T rather than reading as uncovered.
    rna = _measure_pair("ATGAAAGGGCCCTTT", "AUGAAAGGGCCCUUU")
    check_equal(int(rna["comparable"]), 5, "U folds onto T for comparability")
    check_equal(int(rna["synonymous"]), 0, "U folds onto T for classification")


# --- Real-data invariants --------------------------------------------------


def sabin_against_itself() -> None:
    """The definitive frame check: the reference measured against itself is zero.

    If a region column map were wrong, the reference would not be identical to
    itself over those columns and this would not come out zero.
    """
    print("\nSabin against itself, per serotype frame")
    coords = frame.read_region_coordinates()
    for selection in contract.SELECTIONS:
        if selection["id"] not in contract.SABIN_REFERENCE:
            continue
        align = frame.load_alignment(selection["alignment"])
        columns = frame.region_columns(align, selection, coords)
        accession = contract.SABIN_REFERENCE[selection["id"]]
        row = np.array([align.index[accession]])

        for region in contract.DIVERGENCE_REGIONS:
            cols = columns[region]
            refs = reference.References(
                sequences=align.matrix[[align.index[accession]]][:, cols],
                row_index=np.array([0], dtype=np.int32),
                kinds=[reference.KIND_SABIN],
                labels=[accession],
            )
            counts = divergence.measure(align, row, cols, refs)
            label = f"{selection['id']} {region}"
            check_equal(int(counts["synonymous"][0]), 0, f"{label}: synonymous is zero")
            check_equal(
                int(counts["nonsynonymous"][0]), 0, f"{label}: non-synonymous is zero"
            )
            check_equal(int(counts["indel_events"][0]), 0, f"{label}: no indel events")
            check_equal(
                int(counts["comparable"][0]),
                len(cols) // 3,
                f"{label}: every codon comparable",
            )


def region_widths_agree() -> None:
    """The projected frame must reproduce the per-serotype frame's region widths.

    Two independent derivations — the hand-built RF line, and a projection of Sabin 1
    cleavage sites through a genus-wide codon alignment — have to give one answer.
    """
    print("\nregion widths: RF line against Sabin-1 projection")
    coords = frame.read_region_coordinates()
    pv1 = next(s for s in contract.SELECTIONS if s["id"] == "PV1")
    pv1_align = frame.load_alignment(pv1["alignment"])
    from_rf = frame.region_columns(pv1_align, pv1, coords)

    grand = next(s for s in contract.SELECTIONS if s["id"] == "all")
    grand_align = frame.load_alignment(grand["alignment"])
    projected = frame.projected_region_columns(grand_align, coords)
    anchor = grand_align.row(contract.PROJECTION_ANCHOR)

    for region in (contract.REGION_P1, contract.REGION_P2):
        rf_width = len(from_rf[region])
        anchor_width = int((anchor[projected[region]] != frame.NOT_COVERED).sum())
        check_equal(anchor_width, rf_width, f"{region} width agrees between frames")

    # P3 and the polyprotein are one codon short in the projected frame: the CDS
    # block excludes the stop codon that the coordinate table includes.
    for region in (contract.REGION_P3, contract.REGION_POLYPROTEIN):
        rf_width = len(from_rf[region])
        anchor_width = int((anchor[projected[region]] != frame.NOT_COVERED).sum())
        check_equal(
            rf_width - anchor_width, 3, f"{region} differs by exactly the stop codon"
        )


def jitter_is_stable() -> None:
    print("\njitter determinism")
    accessions = ["AY184219", "AB052561", "V01149"]
    first = divergence._jitter(accessions, contract.REGION_P1)
    second = divergence._jitter(accessions, contract.REGION_P1)
    check(
        np.array_equal(first[0], second[0]) and np.array_equal(first[1], second[1]),
        "same inputs produce identical offsets",
    )
    other = divergence._jitter(accessions, contract.REGION_P2)
    check(
        not np.array_equal(first[0], other[0]),
        "a different region produces different offsets",
    )
    check(
        int(np.abs(np.concatenate(first)).max()) <= divergence.JITTER_SCALE,
        "offsets stay within the declared amplitude",
    )


def axes_are_bounded() -> None:
    """x and y must lie in [0, 1] with x + y <= 1, for every record in every panel.

    This is the whole reason indels are charged per affected codon over a denominator
    that includes them. Charging one count per indel *event* against a
    comparable-codon denominator put 349 non-polio records above y = 1, up to 3.3.
    """
    print("\naxis bounds across every built panel")
    import json

    worst = 0.0
    offenders = 0
    checked = 0
    for path in sorted((contract.DATA_OUT / "panels").glob("*.json")):
        payload = json.loads(path.read_text())
        for region, panel in payload["divergence"].items():
            for i in range(len(panel["record"])):
                denominator = panel["assessable"][i]
                if denominator == 0:
                    offenders += 1
                    continue
                total = (panel["synonymous"][i] + panel["nonsynonymous"][i]) / denominator
                worst = max(worst, total)
                if total > 1.0000001:
                    offenders += 1
                checked += 1
            _ = region
    check_equal(offenders, 0, f"no record breaks x + y <= 1 across {checked:,} points")
    check(worst <= 1.0000001, f"worst observed x + y is {worst:.6f}")


def run() -> int:
    synthetic_cases()
    jitter_is_stable()
    region_widths_agree()
    sabin_against_itself()
    if (contract.DATA_OUT / "panels").is_dir():
        axes_are_bounded()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0
