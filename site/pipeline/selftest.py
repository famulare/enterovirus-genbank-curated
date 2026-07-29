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
import distances
import divergence
import embed
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


def distance_and_embedding_cases() -> None:
    """Checks for figure set 2's distance and multidimensional scaling."""
    print("\ndistance and embedding cases")

    # Hand-checkable distances. Six columns, one mismatch, one ambiguity, one gap.
    align = _alignment(
        {
            "same": "ACGTAC",
            "one": "ACGTAG",  # one mismatch over six shared
            "ambig": "ACGTAN",  # N is not comparable: five shared, zero mismatch
            "short": "ACG---",  # three shared, zero mismatch
        }
    )
    rows = np.arange(4)
    shared, matches = distances.counts_against(align.matrix, rows, rows)
    d = distances.distance_from_counts(shared, matches, min_shared=1)
    check_equal(float(d[0, 0]), 0.0, "a sequence against itself is zero")
    check_equal(round(float(d[0, 1]), 6), round(1 / 6, 6), "one mismatch over six shared")
    check_equal(float(shared[0, 2]), 5.0, "an ambiguity code lowers the shared count")
    check_equal(float(d[0, 2]), 0.0, "and contributes no mismatch")
    check_equal(float(shared[0, 3]), 3.0, "a trailing gap lowers the shared count")
    check_equal(float(d[0, 3]), 0.0, "and contributes no mismatch")

    # Overlapping nowhere must be undefined, not distant.
    disjoint = _alignment({"left": "ACGT--", "right": "--ACGT"})
    pair = np.arange(2)
    s2, m2 = distances.counts_against(disjoint.matrix, pair, pair)
    check_equal(float(s2[0, 1]), 2.0, "partially overlapping rows share their overlap")
    far = distances.distance_from_counts(s2, m2, min_shared=50)
    check(bool(np.isnan(far[0, 1])), "too little overlap yields NaN, not a large distance")

    # A landmark set must never contain an undefined pair.
    ragged = _alignment(
        {
            "full1": "ACGTACGTAC",
            "full2": "ACGTACGTAG",
            "full3": "ACGTACGTTC",
            "headonly": "ACGTA-----",
            "tailonly": "-----CGTAC",
        }
    )
    all_rows = np.arange(5)
    chosen = distances.choose_landmarks(ragged.matrix, all_rows, min_shared=6, cap=5)
    matrix = distances.landmark_matrix(ragged.matrix, chosen, min_shared=6)
    check(not np.isnan(matrix).any(), "the landmark matrix has no undefined pair")
    check(len(chosen) >= 3, f"the three full rows are all landmarks (got {len(chosen)})")

    # Classical MDS must recover a geometry it is given exactly.
    truth = np.array([[0.0, 0.0], [3.0, 0.0], [0.0, 4.0], [3.0, 4.0], [1.5, 2.0]])
    exact = np.linalg.norm(truth[:, None, :] - truth[None, :, :], axis=2)
    fitted = embed.Embedding(exact)
    recovered = np.linalg.norm(
        fitted.landmark_coordinates[:, None, :] - fitted.landmark_coordinates[None, :, :],
        axis=2,
    )
    check(
        float(np.abs(recovered - exact).max()) < 1e-8,
        "a planar configuration is recovered to floating-point precision",
    )
    check(fitted.explained > 0.999, f"and two dimensions explain it all ({fitted.explained:.4f})")

    # Nyström must put a known point where it belongs.
    held_out = np.linalg.norm(truth - np.array([3.0, 4.0]), axis=1)
    placed = fitted.place(held_out[None, :])
    offset = float(np.linalg.norm(placed[0] - fitted.landmark_coordinates[3]))
    check(offset < 1e-6, f"an out-of-sample point lands on its own landmark ({offset:.2e})")

    # Orientation must be reproducible, and must not distort the geometry.
    pinned = embed.pin_orientation(fitted.landmark_coordinates, anchor=0)
    again = embed.pin_orientation(fitted.landmark_coordinates, anchor=0)
    check(np.array_equal(pinned, again), "pinning is deterministic")
    check(
        bool((pinned[0] <= 1e-9).all()),
        f"the anchor lands in the lower-left quadrant ({pinned[0]})",
    )
    after = np.linalg.norm(pinned[:, None, :] - pinned[None, :, :], axis=2)
    check(
        float(np.abs(after - exact).max()) < 1e-8,
        "and pinning is a reflection, so every distance survives it",
    )


def embedding_confidence_is_informative() -> None:
    """No region may mark its entire population thin, or the encoding says nothing.

    A fixed 200-column confidence floor once exceeded the whole width of the 3'NCR
    block, so every point in that panel rendered open. The floor is region-relative
    now; this asserts the outcome rather than the rule.
    """
    print("\nembedding confidence is informative in every panel")
    import json

    for path in sorted((contract.DATA_OUT / "panels").glob("*.json")):
        payload = json.loads(path.read_text())
        for region, panel in payload.get("distance", {}).items():
            total = len(panel["record"])
            if total < 20:
                continue
            thin = len(panel["thin"])
            check(
                thin < total,
                f"{payload['selection']} {region}: {thin} of {total} thin, not all of them",
            )


def run() -> int:
    synthetic_cases()
    distance_and_embedding_cases()
    jitter_is_stable()
    region_widths_agree()
    sabin_against_itself()
    if (contract.DATA_OUT / "panels").is_dir():
        axes_are_bounded()
        embedding_confidence_is_informative()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED")
        return 1
    print("all checks passed")
    return 0
