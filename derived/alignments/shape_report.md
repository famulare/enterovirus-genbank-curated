# Alignment shape report

Byte parity with the shipped 2.4.1 alignments is not claimed and is not possible: those bytes came from code that no longer exists in that form, built at an unrecorded thread count. The delta below states exactly what changed instead.

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
