"""The dataset summary the page opens with: real counts, catalogs, and caveats.

Everything here is recomputed from `final/` rather than transcribed, so the page's
numbers cannot drift from the release, and the data-quality caveats shrink on their
own as upstream fixes land. The site never patches a data problem — it reports it.
"""

from __future__ import annotations

import json
import re
from collections import Counter

import contract
import frame
import traits

SCHEMA = 1
_ISO_ANY = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")


def _region_catalog() -> list[dict]:
    return [
        {
            "id": region,
            "label": contract.REGION_LABELS[region],
            "coding": region in contract.CODING_REGIONS,
            "in_divergence": region in contract.DIVERGENCE_REGIONS,
            "in_distance": region in contract.DISTANCE_REGIONS,
            "in_nucleotide_tree": region in contract.NUCLEOTIDE_TREE_REGIONS,
            "in_protein_distance": region in contract.PROTEIN_DISTANCE_REGIONS,
            "in_protein_tree": region in contract.PROTEIN_TREE_REGIONS,
            "min_nt": contract.min_nt(region),
        }
        for region in (
            contract.REGION_5NCR,
            contract.REGION_P1,
            contract.REGION_P2,
            contract.REGION_P3,
            contract.REGION_3NCR,
            contract.REGION_POLYPROTEIN,
        )
    ]


def _trait_catalog(records: list[dict]) -> list[dict]:
    out = []
    for trait in contract.TRAITS:
        entry = {key: trait[key] for key in ("id", "label", "kind") if key in trait}
        entry["scope"] = trait.get("scope", contract.TRAIT_SCOPE_RECORD)
        if trait.get("note"):
            entry["note"] = trait["note"]
        # A declared order overrides frequency ranking, so a rare-but-meaningful
        # category keeps its own hue instead of being folded into Other.
        if trait["id"] in contract.CATEGORY_ORDER:
            entry["order"] = contract.CATEGORY_ORDER[trait["id"]]
        # Selection- and panel-scoped traits have no global value to count.
        if entry["scope"] != contract.TRAIT_SCOPE_RECORD:
            out.append(entry)
            continue
        if trait["kind"] == "discrete":
            values = [str(record.get(trait["id"], "") or "") for record in records]
            present = [value for value in values if value]
            entry["n_present"] = len(present)
            entry["n_distinct"] = len(set(present))
        else:
            present = [
                record.get(trait["id"])
                for record in records
                if record.get(trait["id"]) not in (None, "")
            ]
            entry["n_present"] = len(present)
        out.append(entry)
    return out


def _selection_rows(selection: dict, alignment: frame.Alignment, by_accession: dict) -> list[int]:
    """Row indices of the alignment that belong to this selection."""
    restrict = selection["restrict"]
    if restrict is None:
        return list(range(len(alignment.ids)))
    return [
        index
        for index, accession in enumerate(alignment.ids)
        if (by_accession.get(accession) or {}).get("virus_group") == restrict
    ]


def _canonical_population(selection: dict, records: list[dict]) -> list[dict]:
    if selection["id"] in contract.SABIN_REFERENCE:
        return [record for record in records if record["virus_type"] == selection["id"]]
    if selection["restrict"]:
        return [record for record in records if record["virus_group"] == selection["restrict"]]
    return records


def build_selections(records: list[dict], by_accession: dict) -> tuple[list[dict], list[str]]:
    coords = frame.read_region_coordinates()
    notes: list[str] = []
    cache: dict[str, frame.Alignment] = {}
    out = []

    for selection in contract.SELECTIONS:
        name = selection["alignment"]
        if name not in cache:
            cache[name] = frame.load_alignment(name)
        alignment = cache[name]
        columns = frame.region_columns(alignment, selection, coords)

        rows = _selection_rows(selection, alignment, by_accession)
        aligned_accessions = {alignment.ids[index] for index in rows}
        canonical = _canonical_population(selection, records)
        canonical_accessions = {record["accession"] for record in canonical}

        orphans = sorted(aligned_accessions - set(by_accession))
        if orphans:
            notes.append(
                f"{name}: {len(orphans)} aligned row(s) absent from the canonical table "
                f"({', '.join(orphans[:5])})"
            )

        regions = {}
        for region, cols in columns.items():
            counts = frame.coverage(alignment, cols)[rows]
            threshold = contract.min_nt(region)
            regions[region] = {
                "n": int((counts >= threshold).sum()),
                "columns": int(len(cols)),
                "median_nt": int(sorted(counts)[len(counts) // 2]) if len(counts) else 0,
            }

        concordance = Counter(
            traits.concordance(by_accession[accession], selection["id"], True)
            for accession in aligned_accessions
            if accession in by_accession
        )

        out.append(
            {
                "id": selection["id"],
                "label": selection["label"],
                "alignment": name,
                "frame": selection["frame"],
                "reference": selection["reference"],
                "root": selection["root"],
                "default_trait": selection["default_trait"],
                "n_aligned": len(rows),
                "n_canonical": len(canonical),
                "n_unaligned": len(canonical_accessions - aligned_accessions),
                "n_discordant": concordance.get(contract.DISCORDANT, 0),
                "regions": regions,
            }
        )
    return out, notes


def data_quality(records: list[dict]) -> list[dict]:
    """Live counts for the issues currently present upstream.

    These are reported, never repaired. Each entry shrinks to zero on its own once
    the generation pipeline fixes it, so the page cannot claim a stale caveat.
    """
    findings = []

    non_iso = Counter(
        record["collection_date"]
        for record in records
        if record["collection_date"] and not _ISO_ANY.match(record["collection_date"])
    )
    if non_iso:
        findings.append(
            {
                "id": "collection_date_not_iso",
                "field": "collection_date",
                "n": sum(non_iso.values()),
                "summary": "Dates are not ISO-normalized.",
                "detail": (
                    "Shapes present include "
                    f"{', '.join(repr(value) for value, _ in non_iso.most_common(3))}. "
                    "Month-precision and range values are parsed here; a range resolves to its "
                    "midpoint and a year to mid-year."
                ),
            }
        )

    precision_without_value = sum(
        1
        for record in records
        if record["collection_date_precision"] not in ("", "unknown")
        and not record["collection_date"]
    )
    if precision_without_value:
        findings.append(
            {
                "id": "precision_without_date",
                "field": "collection_date_precision",
                "n": precision_without_value,
                "summary": "Date precision is asserted where no date exists.",
                "detail": (
                    "These records declare a collection-date precision but carry an empty date. "
                    "They are drawn unfilled wherever date is the trait."
                ),
            }
        )

    npev = [record for record in records if record["virus_group"] == contract.GROUP_NPEV]
    scopes = {record["sequence_scope"] for record in npev}
    if len(scopes) == 1:
        findings.append(
            {
                "id": "sequence_scope_polio_only",
                "field": "sequence_scope",
                "n": len(npev),
                "summary": "Sequence scope is uninformative for non-polio records.",
                "detail": (
                    f"Every non-polio record carries {next(iter(scopes))!r}, so the field is "
                    "polio-only in practice and the facet does no work on the non-polio views."
                ),
            }
        )

    duplicated = sum(
        1 for record in records if record["admin1"] and record["admin1"] == record["locality"]
    )
    if duplicated:
        findings.append(
            {
                "id": "admin1_locality_duplicate",
                "field": "locality",
                "n": duplicated,
                "summary": "Locality frequently repeats admin1 verbatim.",
                "detail": (
                    "These records have identical `admin1` and `locality`, so the two columns "
                    "carry one field's worth of information."
                ),
            }
        )

    early = sorted(
        record["collection_date"]
        for record in records
        if record["collection_year"] is not None and record["collection_year"] < 1940
    )
    if early:
        findings.append(
            {
                "id": "implausible_early_dates",
                "field": "collection_date",
                "n": len(early),
                "summary": "A few dates predate enterovirus isolation.",
                "detail": (
                    f"Dated {', '.join(sorted(set(early)))} — earlier than any plausible "
                    "isolation, so likely transcription artifacts rather than genuinely "
                    "archival material."
                ),
            }
        )

    return findings


def consensus_inflation(divergence: dict) -> dict:
    """Size the consensus-coverage artifact described in reference.py's `_consensus`.

    Counted live from the shipped panel for the same reason the `data_quality`
    findings are: this number was carried as hand-written prose from 2.1.5 to 2.4.1
    and was wrong for that whole stretch (the denominator was 13,160, not 13,161)
    because nothing recomputed it. Derived here so it cannot say something the
    artifact does not.

    `assessable` is the denominator of both axes (comparable + indel codons — see
    divergence.py), so the rate is non-synonymous over assessable.
    """
    nonsynonymous = divergence["nonsynonymous"]
    assessable = divergence["assessable"]
    indel_codons = divergence["indel_codons"]

    exceeding = [
        index
        for index, (count, denominator) in enumerate(
            zip(nonsynonymous, assessable, strict=True)
        )
        if denominator and count / denominator > contract.CONSENSUS_INFLATION_RATE
    ]
    numerator = sum(nonsynonymous[index] for index in exceeding)
    indels = sum(indel_codons[index] for index in exceeding)
    return {
        "rate": contract.CONSENSUS_INFLATION_RATE,
        "n_assessed": len(nonsynonymous),
        "n_exceeding": len(exceeding),
        # Share of the exceeding group's non-synonymous numerator contributed by indel
        # codons rather than substitutions — the evidence that the artifact, not
        # divergence, is what puts those records high on the axis.
        "indel_share": indels / numerator if numerator else 0.0,
    }


def build(records: list[dict], by_accession: dict, inflation: dict) -> dict:
    selections, notes = build_selections(records, by_accession)
    release = json.loads(contract.BUILD_MANIFEST.read_text())
    raw = json.loads(contract.RAW_MANIFEST.read_text())
    groups = Counter(record["virus_group"] for record in records)
    statuses = Counter(record["curation_status"] for record in records)

    return {
        "schema": SCHEMA,
        "release": {
            # `schema_version` in the build manifest is the data release version;
            # CITATION.cff carries the same value.
            "version": release["schema_version"],
            "built": release["built"],
            "raw_retrieved": raw["retrieval_date"],
            "validation": release["validation"],
            "n_source_records": release["source_records"],
            "n_records": len(records),
            "n_polio": groups.get(contract.GROUP_POLIO, 0),
            "n_npev": groups.get(contract.GROUP_NPEV, 0),
            "n_vouched": statuses.get("vouched", 0),
            "n_provisional": statuses.get("provisional", 0),
            "n_fields": len(contract.CANONICAL_COLUMNS),
            "n_manual_decisions": sum(
                1 for record in records if record["has_manual_decision"]
            ),
        },
        "defaults": {
            "selection": contract.DEFAULT_SELECTION,
            "region": contract.DEFAULT_REGION,
        },
        "selections": selections,
        "regions": _region_catalog(),
        "traits": _trait_catalog(records),
        "data_quality": data_quality(records),
        "consensus_inflation": inflation,
        "integrity_notes": notes,
        "thresholds": {
            "min_region_nt": contract.MIN_REGION_NT,
            "min_region_nt_by_region": contract.MIN_REGION_NT_BY_REGION,
            "max_discrete_categories": contract.MAX_DISCRETE_CATEGORIES,
        },
    }
