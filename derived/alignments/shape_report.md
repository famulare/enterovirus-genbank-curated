# Alignment shape report

Byte parity with the shipped 2.4.1 alignments is not claimed and is not possible: those bytes came from code that no longer exists in that form, built at an unrecorded thread count. The delta below states exactly what changed instead.

## PV3_unified

- 1597 rows x 7432 nt (3ncr 69, 5ncr 742, cds 6621)
- tiers: {'addon': 246, 'backbone': 1351}
- blocks present: {'3ncr': 288, '5ncr': 327, 'cds': 1503}
- absences: {'3ncr:below_pop_min': 2, '3ncr:empty_fragment': 1119, '3ncr:inferred_no_ncr': 155, '3ncr:no_cds_untranslatable': 33, '5ncr:empty_fragment': 1082, '5ncr:inferred_no_ncr': 155, '5ncr:no_cds_untranslatable': 33, 'cds:no_cds_overlap': 86, 'cds:no_cds_untranslatable': 8}
- CDS translation: 330 of 330 near-complete rows have no internal stop
- CDS columns: 6621 above the 1% floor (2207 codons); 0 sparse, 0 single-row, owned by 0 accession(s)
- residue occupancy: median 900, p10 150, p90 7400, max 7432
- vs 2.4.1: 1425 shipped -> 1597 rebuilt (+263 / -91)
- dropped by reason: {'carve_excluded': 1, 'group_moved': 1, 'serotype_relabelled': 2, 'virus_type_lost': 87}
