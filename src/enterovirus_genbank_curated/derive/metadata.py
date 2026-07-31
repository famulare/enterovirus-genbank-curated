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

Thirteen of the fourteen now have a rule here. `sequence_scope` is the one that does not, and
`PENDING_COLUMNS` says why.

The row *set* is also decided here, by `transport_metadata`'s three inclusion predicates. The third
of them — membership rescue by capsid amino-acid distance — is measured in `derive/evidence.py` and
passed in, so the carve decision stays in this one place while the measurement that feeds it lives
with the other sequence work.

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

# The canonical columns no rule projects at all, and why. Everything else in `CANONICAL_COLUMNS` is
# either transported here or projected by a rule in `registry/rules.json` — which is what this set
# shrinking from twelve entries to one records.
#
# `assert_every_column_is_accounted_for` uses it as the allowlist for a column blank on every row,
# so an entry here is a *declared* absence and a column going blank without one is a build failure.
PENDING_COLUMNS = {
    "sequence_scope": (
        "needs record_type. The sequence stage exists and measures coverage against the Sabin "
        "frame, but coverage does not reproduce record_type: fitted against every threshold "
        "combination it agrees on 86.7% of poliovirus records with systematic rather than boundary "
        "errors — 745 "
        "records the release calls other_fragment have a complete VP1, capsid or genome — so "
        "record_type is not a function of coverage against Sabin VP1 alone. See derive/evidence.py."
    ),
}

# The two records the shipped carve includes and this transport still does not, down from seventeen.
#
# The other fifteen are now reached by the third inclusion predicate — `R-MEMBERSHIP-AA-1`, measured
# in `derive/evidence.measure_membership_rescue` and threaded in as `rescued` below. These two are
# what the declared rule leaves genuinely undecided, and the honest reading is that both are patent
# transcription artifacts rather than real divergence:
#
#   E00765  14.89% capsid AA over 235 codons — its siblings E00766 and E00767 are the same patent's
#           Sabin-1 VP1/VP2 fragments at 0.59% and 0.24%
#   E01571   9.22% capsid AA over 879 codons — its siblings E01570 and E01572 are the same patent's
#           Sabin-1 and Sabin-3 clones at 0.23% and 0.46%
#
# Both sit in R-MEMBERSHIP-AA-1's 8-15% band, which the catalog defines as neither a rescue nor a
# confirmed exclusion, and §5.4 of `docs/engineered-full-population-readjudication.md` raises the
# same question for E01571. Moving the threshold to catch them would be fitting a published
# parameter to two records, so they stay declared here instead: rescuing them needs a curator
# decision about the patent text, not a different number.
SEQUENCE_RESCUED_INCLUSIONS = frozenset({"E00765.1", "E01571.1"})

# The converse gap. AF326751.2 (Simian agent 5 strain B165) carries `Enterovirus` in its GenBank
# lineage, so the genus predicate includes it, but the release ships it as `non_ev_other` with no
# exclusion reason and it has no row in `registry/decisions.tsv`.
#
# The other eight arrived with the membership predicate, and every one of them is a release
# inconsistency rather than a rule that over-reaches. Six are byte-identical to a record the release
# *does* carve, which is the same basis the release itself used to include JA792237-251 and
# PE314016/PH149759 — the digest is shared, so the membership claim cannot differ:
#
#   A08076.1   = A01868.1        HW505760.1 = FB743426.1   HW505761.1 = FB743427.1
#   HW505772.1 = FB743423.1      HW505773.1 = FB743424.1   HW505774.1 = FB743425.1
#
# The remaining two, A06086.1 and A06087.1, are `synthetic construct` patent deposits defined as
# "Synthetic ADN fragment inducing anti-poliovirus antibody formation", sitting 2.32% and 2.10% from
# Sabin 1 in capsid amino acid over 302 and 381 codons. That is poliovirus capsid by any threshold
# the catalog declares.
#
# All nine are recorded rather than resolved: including them is what the declared inputs support,
# and the release's basis for excluding them is not in any input this pipeline can read.
UNDECLARED_EXCLUSIONS = frozenset(
    {
        "AF326751.2",
        "A06086.1", "A06087.1", "A08076.1",
        "HW505760.1", "HW505761.1", "HW505772.1", "HW505773.1", "HW505774.1",
    }
)


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
    included_by_membership_rescue: int


def transport_metadata(
    tables: dict[str, list[dict[str, str]]],
    excluded_accessions: frozenset[str],
    rescued_versions: frozenset[str] = frozenset(),
) -> MetadataTransportResult:
    """Carve the canonical row set and fill every transportable column for it.

    Inclusion is three closed predicates over declared inputs, in this order:

    1. the ledger must not actively exclude the accession — a curator exclusion outranks any
       sequence evidence, so it is checked before anything is measured;
    2. the GenBank lineage names the `Enterovirus` genus; or
    3. `rescued_versions` names the record, which is `R-MEMBERSHIP-AA-1` reaching a record whose
       organism is `unidentified`, `Homo sapiens` or `synthetic construct` but whose sequence is
       poliovirus. Computed in `derive/evidence.measure_membership_rescue` and passed in rather than
       measured here, so this module does not import the sequence stage.

    Nothing else is consulted, so the rows this produces are exactly what the declared inputs
    support — see `SEQUENCE_RESCUED_INCLUSIONS` for the two the shipped carve reaches and this does
    not, and `UNDECLARED_EXCLUSIONS` for the nine the other way round.
    """
    lineage = _lineage_taxa(tables)
    qualifiers = _source_qualifiers(tables)
    biosamples = _biosample_accessions(tables)

    rows: list[dict[str, str]] = []
    by_ledger = 0
    non_enterovirus = 0
    rescued_rows = 0
    for record in tables["records"]:
        record_id = record["record_id"]
        if record["accession"] in excluded_accessions:
            by_ledger += 1
            continue
        if ENTEROVIRUS_GENUS_TAXON not in lineage.get(record_id, set()):
            if record["version"] not in rescued_versions:
                non_enterovirus += 1
                continue
            rescued_rows += 1

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
        included_by_membership_rescue=rescued_rows,
    )
