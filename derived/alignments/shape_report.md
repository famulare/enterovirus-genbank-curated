# Alignment shape report

Byte parity with the shipped 2.4.1 alignments is not claimed and is not possible: those bytes came from code that no longer exists in that form, built at an unrecorded thread count. The delta below states exactly what changed instead.

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
