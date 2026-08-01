# Alignment shape report

Byte parity with the shipped 2.4.1 alignments is not claimed and is not possible: those bytes came from code that no longer exists in that form, built at an unrecorded thread count. The delta below states exactly what changed instead.

## EV_unified

- 24308 rows x 13767 nt (3ncr 87, 5ncr 738, cds 12942)
- tiers: {'addon': 5153, 'backbone': 19155}
- blocks present: {'3ncr': 3447, '5ncr': 4243, 'cds': 24170}
- absences: {'3ncr:annotated_rejected_untranslatable': 32, '3ncr:below_pop_min': 73, '3ncr:empty_fragment': 18504, '3ncr:excluded_oversized': 7, '3ncr:inferred_no_ncr': 2139, '3ncr:no_cds_untranslatable': 106, '5ncr:annotated_rejected_untranslatable': 32, '5ncr:below_pop_min': 20, '5ncr:empty_fragment': 17768, '5ncr:inferred_no_ncr': 2139, '5ncr:no_cds_untranslatable': 106, 'cds:annotated_rejected_untranslatable': 32, 'cds:no_cds_untranslatable': 106}
- CDS translation: 3760 of 3760 near-complete rows have no internal stop
- CDS columns: 6849 above the 1% floor (2283 codons); 6093 sparse, 2994 single-row, owned by 29 accession(s)
- widest insertion owners: MG692415(642cod), MG692413(256cod), OM885400(25cod), AF326751(16cod), MT641370(9cod)
- residue occupancy: median 900, p10 261, p90 7336, max 7459
- vs 2.4.1: 24038 shipped -> 24308 rebuilt (+272 / -2)
- dropped by reason: {'absent_from_canonical': 2}

## NPEV_unified

- 14218 rows x 15423 nt (3ncr 87, 5ncr 738, cds 14598)
- tiers: {'addon': 3799, 'backbone': 10419}
- blocks present: {'3ncr': 1545, '5ncr': 2207, 'cds': 14178}
- absences: {'3ncr:below_pop_min': 40, '3ncr:empty_fragment': 11383, '3ncr:inferred_no_ncr': 1210, '3ncr:no_cds_untranslatable': 40, '5ncr:below_pop_min': 20, '5ncr:empty_fragment': 10741, '5ncr:inferred_no_ncr': 1210, '5ncr:no_cds_untranslatable': 40, 'cds:no_cds_untranslatable': 40}
- CDS translation: 1736 of 1736 near-complete rows have no internal stop
- CDS columns: 6852 above the 1% floor (2284 codons); 7746 sparse, 5205 single-row, owned by 30 accession(s)
- widest insertion owners: PX242045(723cod), MG692415(674cod), MG692413(256cod), OM885400(22cod), AF414372(14cod)
- residue occupancy: median 549, p10 261, p90 7274, max 7459
- vs 2.4.1: 14050 shipped -> 14218 rebuilt (+168 / -0)

## POLIO_unified

- 10090 rows x 7680 nt (3ncr 70, 5ncr 746, cds 6864)
- tiers: {'addon': 1354, 'backbone': 8736}
- blocks present: {'3ncr': 1902, '5ncr': 2036, 'cds': 9992}
- absences: {'3ncr:annotated_rejected_untranslatable': 32, '3ncr:below_pop_min': 33, '3ncr:empty_fragment': 7121, '3ncr:excluded_oversized': 7, '3ncr:inferred_no_ncr': 929, '3ncr:no_cds_untranslatable': 66, '5ncr:annotated_rejected_untranslatable': 32, '5ncr:empty_fragment': 7027, '5ncr:inferred_no_ncr': 929, '5ncr:no_cds_untranslatable': 66, 'cds:annotated_rejected_untranslatable': 32, 'cds:no_cds_untranslatable': 66}
- CDS translation: 2024 of 2024 near-complete rows have no internal stop
- CDS columns: 6651 above the 1% floor (2217 codons); 213 sparse, 72 single-row, owned by 6 accession(s)
- widest insertion owners: OR538732(10cod), OR208612(5cod), OR208596(3cod), OR538740(3cod), OR208609(2cod)
- residue occupancy: median 906, p10 246, p90 7413, max 7442
- vs 2.4.1: 9988 shipped -> 10090 rebuilt (+106 / -4)
- dropped by reason: {'absent_from_canonical': 2, 'group_moved': 2}

## PV1_unified

- 4337 rows x 7441 nt (3ncr 69, 5ncr 742, cds 6630)
- tiers: {'addon': 717, 'backbone': 3620}
- blocks present: {'3ncr': 386, '5ncr': 432, 'cds': 4093}
- absences: {'3ncr:annotated_rejected_untranslatable': 29, '3ncr:below_pop_min': 11, '3ncr:empty_fragment': 3562, '3ncr:inferred_no_ncr': 343, '3ncr:no_cds_untranslatable': 6, '5ncr:annotated_rejected_untranslatable': 29, '5ncr:empty_fragment': 3527, '5ncr:inferred_no_ncr': 343, '5ncr:no_cds_untranslatable': 6, 'cds:no_cds_overlap': 239, 'cds:no_cds_untranslatable': 5}
- CDS translation: 386 of 390 near-complete rows have no internal stop; exceptions ['EF456706', 'FV537075', 'FV537076', 'FV537077']
- CDS columns: 6630 above the 1% floor (2210 codons); 0 sparse, 0 single-row, owned by 0 accession(s)
- residue occupancy: median 906, p10 150, p90 2643, max 7441
- vs 2.4.1: 3732 shipped -> 4337 rebuilt (+717 / -112)
- dropped by reason: {'absent_from_canonical': 1, 'serotype_relabelled': 12, 'virus_type_lost': 99}

## PV2_unified

- 3790 rows x 7439 nt (3ncr 68, 5ncr 747, cds 6624)
- tiers: {'addon': 356, 'backbone': 3434}
- blocks present: {'3ncr': 1200, '5ncr': 1247, 'cds': 3655}
- absences: {'3ncr:below_pop_min': 18, '3ncr:empty_fragment': 2199, '3ncr:excluded_oversized': 7, '3ncr:inferred_no_ncr': 339, '3ncr:no_cds_untranslatable': 27, '5ncr:empty_fragment': 2177, '5ncr:inferred_no_ncr': 339, '5ncr:no_cds_untranslatable': 27, 'cds:no_cds_overlap': 111, 'cds:no_cds_untranslatable': 24}
- CDS translation: 1225 of 1225 near-complete rows have no internal stop
- CDS columns: 6624 above the 1% floor (2208 codons); 0 sparse, 0 single-row, owned by 0 accession(s)
- residue occupancy: median 903, p10 891, p90 7434, max 7439
- vs 2.4.1: 3604 shipped -> 3790 rebuilt (+357 / -171)
- dropped by reason: {'absent_from_canonical': 1, 'group_moved': 1, 'serotype_relabelled': 23, 'virus_type_lost': 146}

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
