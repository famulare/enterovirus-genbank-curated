# Frozen legacy registries

Four CSVs, committed byte-identically from the private curation repository on 2026-07-29 and pinned
by sha256 in [`tests/test_legacy_registry.py`](../../tests/test_legacy_registry.py).

**This directory is provenance, not input. Nothing in the build reads it** — a test enforces that,
because a future stage that started reading these files would reintroduce exactly the frozen-upstream
dependency this rewrite exists to remove.

## Why they are here rather than re-derived

They are the only surviving output of two pipeline stages whose external inputs no longer exist. The
shipped release says so itself, machine-readably, in `final/audit/build_manifest.json`:

| stage | external input | status |
|---|---|---|
| `extract_genbank_metadata.py` | `~/Downloads/prepareAlignments/titleList_withKeys_merged.xlsx`, `amendedClassification.csv` | **gone from disk** (checked 2026-07-28) |
| `reconstruct_archival_wpv1_dates.py` | a sibling repo + a second external project, both by absolute path | unrunnable; see the dead-code finding below |

Neither stage is being ported. One is dead code; the other reduces to 30 rows that are already
migrated into the ledger. So these files cannot be regenerated, and pinning them by hash is the only
honest way to carry them: an accidental edit, a re-export, or a line-ending change fails a test
rather than quietly redefining history.

Three of the four — `legacy_title_key_table.csv`, `legacy_accession_classification_overrides.csv`,
`legacy_date_location_extract.csv` — are named in that manifest's `input_provenance_caveats` as
frozen **inputs-of-record**. Until this commit they were dangling references in the published repo:
the manifest asserted a dependency on files the repo did not contain. That is the actual reason to
commit them, and it is stronger than "completeness". `legacy_2026_bridge.csv` is not manifest-named;
it is carried because it is the third output of the same vanished stage that carries curator
judgement forward, and leaving it behind is how a reader concludes a file was suppressed. It is not
itself hand-maintained — `build_legacy_bridge(legacy_title_rows, metadata_rows)` derives it by
joining the hand-curated title table against freshly parsed GenBank metadata — but every judgement
column in it (`possibleClassifications`, `possibleSamplingFrames`, `discard`, `reason`, `notes`) is
carried through from the hand-curated side.

## What each file actually reaches

Verified by reading the private pipeline, not inferred from the plan. Both `to_csv` and the project's
`write_csv` wrapper were grepped, since the two stages use different writers.

| file | rows | written by | read by | effect on canonical output |
|---|---:|---|---|---|
| `legacy_accession_classification_overrides.csv` | 30 | `extract_genbank_metadata.py` | `build_release_v2.py` → `decision_source_specs()`; also the two artifact scanners, which only re-emit it as `legacy_override_classification` | **YES** — the only load-bearing file, via `build_release_v2.py` alone. All 30 rows are migrated into `registry/decisions.tsv` as `legacy_classification_override` decisions |
| `legacy_title_key_table.csv` | 314 | `extract_genbank_metadata.py` | nothing — named only inside a caveat string | none |
| `legacy_2026_bridge.csv` | 314 | `extract_genbank_metadata.py` | 5 scripts, all evidence / scan / review-queue only | none |
| `legacy_date_location_extract.csv` | 1,657 | `reconstruct_archival_wpv1_dates.py` | `infer_genbank_metadata.py` | row count only — three scalars in a summary `.md` |

`legacy_2026_bridge.csv`'s non-reach was established by enumerating its readers and tracing each,
because "probably unused" is not good enough for a file this size. All five:

1. `curate_origin_unknown.py` uses it only to append prose to a `decision_evidence` field, and the
   downstream curated-metadata builder consumes only that file's `recommended_*` columns.
2. `scan_vdpv_classification_artifacts.py` emits `final_classification_suggestion` into
   `vdpv_accession_scan.csv`. That is the chain that has to be traced, and it stops:
   `finalize_curated_classification.py` reads that one file, appends the column to the working
   master under the name `classification_scan`, and **nothing reads it again**. The public
   `poliovirus_classification` comes from `classification_reconciled`, computed by
   `reconcile_sequence_classification.py` from the text `classification`, the BS2 sequence tier, and
   the locked `vdpv_wild_reconciliation.csv` allowlist, which takes precedence over the computed
   call. What matters here is the negative: that script reads neither the bridge nor
   `classification_scan`. Nor does `classification_scan` appear in the private shipped carve or in
   `final/canonical/sequence_metadata.tsv.gz`; it is a parked human-review signal the automated
   reconciliation deliberately does not consume, dropped whenever the master is rebuilt.
3. `scan_ivdpv_classification_artifacts.py` is the iVDPV counterpart. Its output,
   `ivdpv_p0_accession_scan.csv`, has **zero code readers** — it does not feed
   `finalize_curated_classification.py`, which reads only the VDPV scan.
4. `build_metadata_review_queues.py` emits a human review queue, and the judgments humans produced
   from it are already in the ledger as decisions.
5. `build_dq_existing_evidence_classification_audit.py` writes a CSV and a summary `.md` under
   `working/classification_label_review/`. Its CSV is read by reader 2 and by
   `resolve_dq264_vp1_sequence_classification.py`, so it is not terminal — but both routes reach
   canonical output only through `classification_scan`, which by item 2 reaches nothing.

So of 2,315 legacy rows carried here, **30 are load-bearing**, and those 30 are migrated. The rest is
audit trail: it lets a reader check the migration rather than take it on trust, which is the point of
`source_artifact` naming a file that is now committed beside the ledger.

## `reconstruct_archival_wpv1_dates.py` is dead code

Stated here as well as in [`docs/pipeline.md`](../../docs/pipeline.md) so that a reader who arrives at
this directory first does not go looking for a missing stage. It writes six CSVs and a summary `.md`;
five of the six have zero consumers anywhere in the private repository, and the sixth contributes
only three row-count scalars to that summary. It declares **three** inputs by absolute path across
two other repositories, and its hard-coded working directory — where it both reads the third input
and writes every output — is a path inside one of them that does not exist today. Two of the three
inputs are present and tracked; the third, `genbank_metadata.csv`, is absent from its repository's
git history, which is why the stage is not reconstructible now. Its scientific conclusions already
survive as registry rows migrated in stage 2.

## Deliberately not carried

The same manifest caveat names three more frozen outputs of `extract_genbank_metadata.py`:
`genbank_metadata.csv`, `genbank_features.csv`, `genbank_project_triage.csv`. They are **not** here,
on purpose.

They are large derived outputs of the 13-step mutable master pipeline — the thing Phase B replaces.
Committing them would import the exact dependency this rewrite removes, and would make a
non-reproducible 46 MB table look like a legitimate public input. The three files above are
hand-maintained curation rows with no upstream left; these three are machine output with an upstream
that is being rebuilt. The asymmetry is the whole distinction, so it is recorded rather than left to
look like an oversight.

## DQ205099 — the fourth `engineered` call

`legacy_accession_classification_overrides.csv` asserts `classification=engineered` for **four**
accessions. Three of them are the D2 trio (`CS406436`, `CS406482`, `CS406483`), superseded by the
2026 review. The fourth is `DQ205099`, and it is still `active`.

It survived D2 because **nothing contradicted it**: it has exactly one decision in the entire ledger
and no 2026 manual review row, so it never appeared as a conflict. "No reviewer objected" is the
reason it survived, not evidence that anyone checked it — and that is worth stating plainly, because
it is the failure mode this whole directory is meant to make visible.

Checked on its merits in stage 4, it is **not** a D2 twin, and the difference is not subtle:

| | D2 trio | DQ205099 |
|---|---|---|
| GenBank division | `PAT` | `VRL` |
| definition | `Sequence 6/52/53 from Patent WO2006042156` | `Human poliovirus 2 clone S2R9, complete genome` |
| molecule type | DNA | RNA |
| source qualifiers | — | `clone=S2R9`, `note=infectious clone` |
| what it is | parental MEF1, lifted into a patent filing | the parental control clone of the study the patent derives from |

The legacy row's stated *mechanism* is false: measured divergence from Sabin 2 (`AY184220`) is
**3 nt over 7,439 aligned nt (0.040%)**, with the differences `A2616G` / `A3303T` / `T5640A`
unclustered across P1 and P3. Capsid codon deoptimization rewrites synonymous codons wholesale and
would put hundreds of changes inside ~2.6 kb. `DQ205099` is the wild-type control of
Burns *et al.* 2006, *J. Virol.* 80:3259 (PMID 16537593), not one of that paper's deoptimized
constructs.

The legacy row's *label* is nonetheless correct. The record's own annotation says
`note=infectious clone`, and an infectious cDNA clone is a construct. So canonical's
`engineered_or_construct=TRUE`, `surveillance_stream=engineered/lab`, `sample_origin=non-human` and
`poliovirus_classification=Sabin-like` all stand, and applying D2's remedy here would make the record
*less* accurate rather than more.

**Disposition (curator, 2026-07-29): annotate, do not adjudicate.** The row keeps `status=active`
and its verbatim curator text; the falsification is recorded in `notes`. No shipped value changes.
Four tests pin this so it is not rediscovered and re-escalated: that the file asserts `engineered`
four times, that only three of the four are division `PAT`, that the fourth is annotated *and* still
`active`, and that it still has exactly one decision in the ledger.
