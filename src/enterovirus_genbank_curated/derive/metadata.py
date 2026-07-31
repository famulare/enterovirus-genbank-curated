"""Transport source values into canonical metadata columns.

This is the *transport* half of canonical metadata: the columns whose shipped value is a
GenBank value moved into a canonical column, with at most a documented, closed-form
transformation. It deliberately stops short of the derivation half — the columns whose value
comes from sequence comparison against a reference panel or from the curated master — because
those inputs do not exist in this clone. `PENDING_COLUMNS` names each one and why.

The split is not a judgement call. `final/audit/canonical_projection_provenance.tsv.gz` carries a
row for exactly fourteen canonical columns, naming the upstream field each was projected from;
those fourteen are the derived half, minus `locality`, whose projection is a closed-form rule over
one GenBank string (R-GEO-LOCALITY-1) and so transports. The remaining twelve columns carry no
projection row because there is no projection: the value is the source value.

Two things this module must not do, both of them boundary 1 in `docs/pipeline.md`:

* read anything under `final/` — the shipped release is the comparison target, never an input;
* consult the residual sets below to fix up its own output. `verify_metadata_parity` uses them to
  state a known gap; the build does not see them. A transport that patched itself against a
  declared diff would pass parity while proving nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

from enterovirus_genbank_curated.derive.geo import GEO_QUALIFIER, parse_geo_loc_name

# Canonical column <- `records` column, for the columns that are a straight rename or identity.
RECORD_COLUMNS = {
    "accession": "accession",
    "version": "version",
    "sequence_sha256": "sequence_sha256",
    "sequence_length_nt": "sequence_length_nt",
    "ncbi_taxid": "ncbi_taxid",
    "organism_name": "organism_name",
}

# Canonical column <- first value of this qualifier on the record's `source` feature.
QUALIFIER_COLUMNS = {
    "isolate_name": "isolate",
    "strain_name": "strain",
    "host_name": "host",
}

GEO_COLUMNS = ("country", "admin1", "locality")
BIOSAMPLE_DATABASE = "BioSample"
SOURCE_FEATURE_KEY = "source"
ENTEROVIRUS_GENUS_TAXON = "Enterovirus"

TRANSPORTED_COLUMNS = (
    *RECORD_COLUMNS,
    *QUALIFIER_COLUMNS,
    *GEO_COLUMNS,
    "biosample_accession",
)

# Why each remaining canonical column is out of reach from `raw/` + `registry/` alone. Every reason
# here is an input that is absent from this clone, not an unwritten function.
PENDING_COLUMNS = {
    "sequence_scope": "needs record_type, derived by aligning against Sabin VP1 coordinates",
    "virus_group": (
        "needs dataset_partition; poliovirus membership is sequence-adjudicated for 417 records "
        "whose organism name is generic (R-MEMBERSHIP-AA-1)"
    ),
    "virus_type": "needs the coverage-guarded serotype and sequence-derived EV typing",
    "poliovirus_classification": "needs classification_reconciled, a sequence/text reconciliation",
    "curation_status": "follows virus_group",
    "sample_origin": "projects the curated origin_class, held only in the curated master",
    "surveillance_stream": "projects the curated sampling_frame, held only in the curated master",
    "specimen_type": "projects the curated specimen_type, held only in the curated master",
    "collection_date": "precision-driven and curated-first; needs collection_date_curated",
    "collection_date_precision": "projects the curated collection_date_precision",
    "collection_year_earliest": "needs the curated date-range parse",
    "collection_year_latest": "needs the curated date-range parse",
}

# The shipped carve includes these seventeen records; this transport cannot. All are patent-division
# deposits whose organism is `unidentified`, `Homo sapiens` or `synthetic construct`, so the genus
# predicate below rejects them, and they were recovered upstream by capsid amino-acid distance to a
# poliovirus reference (R-MEMBERSHIP-AA-1). Eight name polio in their DEFINITION, but nine do not,
# so no text rule recovers the set — it needs the sequence stage.
#
# Curator disposition, 2026-07-30: these records **belong** in the carve. So this is a gap to close
# by implementing the membership rule, not a set to carve-exclude — dropping them would remove real
# poliovirus sequence from the release.
SEQUENCE_RESCUED_INCLUSIONS = frozenset(
    {
        "E00765.1", "E00766.1", "E00767.1", "E00768.1", "E00769.1",
        "E01570.1", "E01571.1", "E01572.1",
        "HV932178.1",
        "JA792237.1", "JA792238.1", "JA792249.1", "JA792250.1", "JA792251.1",
        "MA400487.1", "PE314016.1", "PH149759.1",
    }
)

# The converse gap, and a smaller one. AF326751.2 (Simian agent 5 strain B165) carries `Enterovirus`
# in its GenBank lineage, so the genus predicate includes it, but the release ships it as
# `non_ev_other` with no exclusion reason and it has no row in `registry/decisions.tsv`. The call is
# real but its basis is not in any declared input, so it is recorded rather than guessed at.
UNDECLARED_EXCLUSIONS = frozenset({"AF326751.2"})


def _lineage_taxa(tables: dict[str, list[dict[str, str]]]) -> dict[str, set[str]]:
    lineage: dict[str, set[str]] = {}
    for row in tables["record_taxonomy"]:
        lineage.setdefault(row["record_id"], set()).add(row["taxon_name"])
    return lineage


def _source_qualifiers(tables: dict[str, list[dict[str, str]]]) -> dict[tuple[str, str], str]:
    """First value of each qualifier on each record's `source` feature.

    "First" is the parser's emission order, which is record, then feature ordinal, then qualifier
    and value ordinal — so this is the first value on the earliest `source` feature that carries the
    qualifier at all. Five records in the corpus have two `source` features, which is the only
    reason the tie-break needs stating.
    """
    source_features = {
        row["feature_id"]
        for row in tables["features"]
        if row["feature_key"] == SOURCE_FEATURE_KEY
    }
    first: dict[tuple[str, str], str] = {}
    feature_record = {row["feature_id"]: row["record_id"] for row in tables["features"]}
    for row in tables["feature_qualifiers"]:
        feature_id = row["feature_id"]
        if feature_id not in source_features:
            continue
        first.setdefault(
            (feature_record[feature_id], row["qualifier_name"]), row["qualifier_value"]
        )
    return first


def _biosample_accessions(tables: dict[str, list[dict[str, str]]]) -> dict[str, str]:
    first: dict[str, str] = {}
    for row in tables["record_xrefs"]:
        if row["database_name"] == BIOSAMPLE_DATABASE:
            first.setdefault(row["record_id"], row["identifier"])
    return first


@dataclass(frozen=True)
class MetadataTransportResult:
    rows: list[dict[str, str]]
    excluded_by_ledger: int
    excluded_as_non_enterovirus: int


def transport_metadata(
    tables: dict[str, list[dict[str, str]]], excluded_accessions: frozenset[str]
) -> MetadataTransportResult:
    """Carve the canonical row set and fill every transportable column for it.

    Inclusion is two closed predicates over declared inputs: the GenBank lineage must name the
    `Enterovirus` genus, and the ledger must not actively exclude the accession. Nothing else is
    consulted, so the rows this produces are exactly what the declared inputs support — see
    `SEQUENCE_RESCUED_INCLUSIONS` for the seventeen the shipped carve reaches and this does not.
    """
    lineage = _lineage_taxa(tables)
    qualifiers = _source_qualifiers(tables)
    biosamples = _biosample_accessions(tables)

    rows: list[dict[str, str]] = []
    by_ledger = 0
    non_enterovirus = 0
    for record in tables["records"]:
        record_id = record["record_id"]
        if record["accession"] in excluded_accessions:
            by_ledger += 1
            continue
        if ENTEROVIRUS_GENUS_TAXON not in lineage.get(record_id, set()):
            non_enterovirus += 1
            continue

        row = {column: record[source] for column, source in RECORD_COLUMNS.items()}
        for column, qualifier in QUALIFIER_COLUMNS.items():
            row[column] = qualifiers.get((record_id, qualifier), "")
        geo = parse_geo_loc_name(qualifiers.get((record_id, GEO_QUALIFIER), ""))
        row["country"] = geo.country
        row["admin1"] = geo.admin1
        row["locality"] = geo.locality
        row["biosample_accession"] = biosamples.get(record_id, "")
        rows.append(row)

    return MetadataTransportResult(
        rows=rows,
        excluded_by_ledger=by_ledger,
        excluded_as_non_enterovirus=non_enterovirus,
    )
