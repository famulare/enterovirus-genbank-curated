# Reproducibility boundary

## Current state

**`final/` is what this pipeline builds.** As of 2026-08-01 it holds release 4.1.0 — 4.0.0 plus
thirteen accession-level `poliovirus_classification` decisions, no rule or threshold change: canonical,
audit and curation trees written by `evgc build-metadata` from `raw/` and `registry/` alone, and
alignments written by `evgc alignment-build` from those. It is a build destination now, not a parity
target, and `build.reject_immutable_output` guards only `raw/` — the frozen input of record, where a
build that can overwrite its own input has no oracle left at all.

The 2.4.1 release it replaced is not gone. `releases/2.4.1/parity.json` still describes the raw
archive, and `releases/2.4.1/alignments/` holds the nineteen carved-in alignment files, which is
what `evgc alignment-shape` still measures the rebuild's declared delta against. What retired with
the promotion is the *metadata* parity gate: comparing the build to `final/` cell by cell would now
read the build's own bytes and pass by construction, and a gate that cannot fail is worse than an
absent one. `evgc check-declines` replaced it with a claim that needs no oracle — the build declines
exactly where this repository declares it declines.

What that does *not* mean: 4.0.0 is not 2.4.1 rebuilt. It carves 24,308 rows against the shipped
24,301, it declines values the release asserts, and it supersedes some the release got wrong. Every
one of those differences is declared as a count or a witness rather than absorbed, and the rest of
this document is the accounting. One structural gap remains open and has its own section:
`sequence_scope` is the one canonical column still unwritten.

**Reproducible today — `final/source/`.** `evgc parity-source` re-authenticates
`raw/sequence.gb.zip`, reparses all 25,727 records, and compares every one of the twelve
normalized relations plus their twelve Parquet counterparts against the `file_bytes` hashes
declared in `final/audit/release_file_manifest.tsv`. All twenty-four match byte-for-byte, and
repeated builds are byte-stable. Only `genbank_source.duckdb` is excluded, because DuckDB file
bytes are not reproducible; the manifest records a logical-content hash for it.

**Rebuilt, and no longer compared — `final/canonical/sequence_metadata.tsv.gz`.** `evgc
build-metadata` writes it from `raw/sequence.gb.zip` and `registry/decisions.tsv` alone. Until
2026-08-01 `evgc parity-metadata` compared the rebuild to the shipped table cell by cell; that
comparison retired with the promotion, because `final/` now holds what the build writes. What it
established while it ran is recorded below and did not stop being true — it stopped being
*checkable* against this tree, which is a different thing and worth saying plainly.

```bash
evgc check-declines    # the successor: every declined cell equals its declared count
```

This was a *transport* claim, not a claim on the table. Thirteen of the twenty-six canonical columns
hold a GenBank value moved into a canonical column — `accession`, `version`, `sequence_sha256`,
`sequence_length_nt`, `ncbi_taxid`, `organism_name`, `isolate_name`, `strain_name`, `host_name`,
`country`, `admin1`, `locality`, `biosample_accession`. Every one of those cells matches the
release exactly, in the same row order, and repeated builds are byte-stable. The split is not a
judgement call: `final/audit/canonical_projection_provenance.tsv.gz` carries a projection row for
exactly the other fourteen columns, minus `locality`, whose rule is closed-form over one GenBank
string.

`locality` is also produced *with its provenance*, and it was the deliberately small first column for
that: reproducing a value while mislabelling which way the rule went is right by luck, so the cheapest
place to establish that the rule catalog, the outcome type and the provenance writer all agree with the
release is on one closed-form rule before a harder column is attempted. Its **value** matches the
release on all 24,299 shared records. Its **branch label** does not, and comparing the label is what
found that the shipped label was wrong — see [the second deliberate break](#the-second-deliberate-break-localitys-basis).

`virus_group` and `curation_status` are projected the same way, and they are where the rewrite first
**declines** rather than guessing. Poliovirus sits inside one enterovirus species — *Enterovirus C*,
renamed *Enterovirus coxsackiepol* — so a GenBank organism name decides membership only when it names
something at or below the type level. Six names cannot: the polio-containing species under either
name, the bare genus, and three that are not virus identifications at all (`unidentified`,
`synthetic construct`, `Homo sapiens`). The rule returns unresolved for all of them.

That matters more than it looks. Defaulting those names to non-polio scored **98.3%** against the
release when it was measured, which reads as success and was a guess on 414 records — and
`virus_group` gates `sequence_scope`, `curation_status`, `poliovirus_classification` and the whole epi
partition, so four later columns would inherit the guess and each look right for the wrong reason.
The honest population is the declined rows, not the disagreements: sizing an ambiguity by its
disagreements rather than by its inputs is the specific mistake being avoided here. (The 98.3% and
414 are as measured against the then-current declined population of 1,832. Curated-classification
entailment has since resolved part of it and neither figure has been re-measured; the argument does
not depend on the exact values.)

The declined population is now **1,596 rows** — `oracle/parity.py`'s `UNRESOLVED_PARTITION_ROWS`,
which the parity gate checks rather than trusts. Of the remaining 22,703 of 24,299 shared rows, every
one matches the release, including `manual_override` — TRUE on exactly the seventeen records the
ledger's `is_poliovirus` decisions resolve. That is the first place a recorded decision is shown to
reach a generated provenance row rather than merely existing in the ledger, which is the D2 failure
stated positively.

### Being hash-gated is not the same claim as being regenerable

`final/audit/release_file_manifest.tsv` covers 38 of the 58 files in `final/`; the other twenty had
no hash anywhere at all, so truncating all nineteen `final/alignments/` files to zero bytes and
deleting one outright left every gate reporting PASS. `oracle.release.verify_release_manifest_hashes`
now recomputes all thirty-seven `file_bytes` hashes the manifest declares (previously six were), and
`verify_manifest_completeness` requires every file under `final/` to be covered by either the
manifest or `oracle.release.CARRIED_FINAL_FILES` — bidirectionally, so an undeclared new file fails
as loudly as a deleted declared one. The twenty carried hashes are pinned in
`tests/test_carried_files.py`, in code rather than in a new `releases/2.4.1/parity.json` key, because
a data key would give them a single declaration computed from the very bytes it gates and movable by
a data edit.

None of this makes `final/alignments/` reproducible. It makes it *immutable in a way something
checks*, which is the weaker property that was missing. See "The alignment layer" below for what
*is* reproducible there today.

### The first deliberate break: `collection_date_precision`

The date family does not reproduce the release, on purpose. This is the first place the rewrite
corrects rather than reproduces, and the second follows it.

For every record that deposited a `/collection_date`, the canonical date **is** the ISO normalization
of that qualifier and the precision **is** its shape — 19,732 carved records, no curated input,
including the floor-of-mean midpoint on all 121 interval records. The release describes these as
projections of curated fields; for these rows those curated fields evidently just held the normalized
source value.

The problem is the 4,569 records that deposited **no** date. The release splits them: 2,805 get
precision `unknown`, and 1,764 get precision `year` with a year recovered outside GenBank by an
archival reconstruction whose inputs are not in this repository. Nothing in `raw/` separates those two
groups, so the split cannot be reproduced, and guessing it would fabricate 4,569 values.

**Curator decision, 2026-07-30: a record with no date has no precision.** Those rows now carry `NA`
and a blank date.

**Invariant broken, and its replacement.** 2.4.1 guaranteed
`collection_date_precision ∈ {day, month, year, range, unknown}` and said nothing relating the
precision to the value. The vocabulary is now `{day, month, year, range, NA}` — `unknown` retired,
`NA` new — under a stronger guarantee that ties the two columns together:

> `collection_date` is blank if and only if `collection_date_precision` is `NA`.

That is checkable in both directions and both matter: a blank date with a real precision claims a
determination about a date that is not there, and a populated date with `NA` claims no determination
about one that is. It is enforced against the build's own output by `validation/invariants.py` before
anything is written, so it holds for a fresh clone with no `final/` present and cannot be satisfied by
copying. `unknown` is also freed to mean what it says — a date exists but its precision is unclear.

The break is counted, not just described: **1,761** records differ on `collection_date` and **4,549**
on `collection_date_precision`, declared in `oracle/parity.py` and required to match exactly, so a
deliberate delta changing size fails the gate. The 1,764 whose year came from identifier parsing are
recoverable later — the frozen archival-dates extract labels 21 identifier rule families, usable as a
validation oracle rather than an input — and each one recovered moves a row from `NA` back to `year`,
never the reverse.

R-DATE-1 and R-DATE-PRECISION-1 are therefore `deprecated` in the catalog and superseded by R-DATE-2
and R-DATE-PRECISION-2 on real semver. `final/audit/rules.tsv.gz` still regenerates byte-for-byte,
because the view emits only rules carrying the baseline's own `rule_version` — which is how the
catalog can evolve without moving a published artifact.

### `specimen_type`: the first column recovered from text rather than projected

`sample_origin`, `surveillance_stream` and `specimen_type` all shipped as `canonical_projection` of a
curated-master field, so 24,301 values carry no record of how they were decided. `specimen_type` is
the first one recovered.

R-SPECIMEN-2 matches one regex per category against `/isolation_source`, after an active ledger
`specimen_type` decision. Over the carved records it **resolves 11,608, declines 12,700 rather than
guessing, and disagrees with the release on one**. The patterns are declared in the catalog, and the
decline count is `oracle/parity.py`'s `UNRESOLVED_SPECIMEN_ROWS`.

Two rule defects came out of reading the disagreements one at a time instead of tuning a rate:
`"throat swab and stool samples"` names two specimens, so more than one matching category is now
declined rather than settled by pattern order (4 records); and a bare `fec` pattern was firing inside
"in**fec**tion", mislabelling two respiratory records as stool. One disagreement is left standing
rather than absorbed: `GQ331952.1` deposits `groundwater` and ships `stool`, which is a probable
upstream error, and a rule bent to reproduce a wrong value would be worse than a declared
disagreement.

**`sample_origin` and `surveillance_stream` are now projected, and they decline heavily — 3,682 and
8,650 rows respectively (`UNRESOLVED_ORIGIN_ROWS`, `UNRESOLVED_STREAM_ROWS`). The measurement below is
why the declines are that large rather than a rule being pushed to cover them.** Their ceilings were
measured over progressively richer feature sets:

| feature set | groups | `sample_origin` | `surveillance_stream` |
|---|---|---|---|
| host + isolation_source + environmental_sample | 160 | 96.5% | 90.3% |
| + lab_host + collected_by | 176 | 96.5% | 92.3% |
| + note | 442 | 97.5% | 93.5% |
| + definition | **9,951** | 99.9% | 99.9% |

That last row is worthless, and it nearly went in as a success. 9,951 groups over 10,084 poliovirus
records means `definition` is very nearly a unique key per record: the "ceiling" is measuring how well
a record predicts itself, not how well a rule would generalize. A rule built on it would be
memorizing the oracle. On the feature sets that do generalize, roughly 250 and 650 records are
irreducibly ambiguous and belong in a curation queue rather than in a rule.

### What a decline turns into: the curation queue

Declining honestly is only half the design. `evgc build-metadata` now also writes
`curation/curation_queue.tsv`, and it is what stops `unresolved_reason` being a note nobody acts on.

**28,392 declined cells collapse into 302 groups**, because records decline for the *same* reason:
every record whose `/isolation_source` is `conjunctival swab` is one decision, not 462. The queue is
keyed on the input the rule examined and could not decide from, so resolving one group resolves every
record in it. `queue_id` is derived from that content rather than allocated sequentially, so
re-running the build does not renumber an in-flight worksheet.

Three properties are worth stating because each is a failure mode avoided:

- **`registry_field`, not the canonical column.** A curator resolving `sample_origin` must file
  against `origin_class`. A decision filed under the canonical name would validate, sit in the ledger,
  and change nothing — the D2 failure exactly. The queue names the field a resolution has to use.
- **`suggested_resolution_kind` keeps boundary 3 operational.** A call about one subject is a
  `decision`; a mapping that generalizes is a `rule_parameter` change with a version bump. Encoding a
  general rule as 2,000 identical decisions would bury it in curation history.
- **Consequential declines are not queued.** `curation_status` declines only because `virus_group`
  did, so queueing both would ask for twice the decisions that exist. A queue that overstates its
  own size is worse than no queue.

It is **not** a diff against the release. Every row is knowable from `raw/` and `registry/` at build
time with no `final/` present. Where the rewrite *disagrees* with shipped values is a separate
artifact, because merging the two would let the release become a pipeline input with a human as the
transport.

### The second deliberate break: `locality`'s basis

The same defect, found by the same method. 2.4.1 labels **every** blank `locality`
`duplicate_of_admin1_suppressed`. Measured, only **4,233 of 23,268** are suppressions:

| n | what the record deposited | the release said | the rewrite says |
|---|---|---|---|
| 4,233 | `Country: Region` | suppressed | `duplicate_of_admin1_suppressed` |
| 16,987 | `Country` only, no region | suppressed | `no_admin1_deposited` |
| 2,048 | no `/geo_loc_name` at all | suppressed | `no_geography_deposited` |

So the label asserts a determination that was never made on 19,035 records. The two new bases stay
distinct deliberately: a record naming only a country *did* deposit geography, so folding it into
"nothing deposited" would replace one overstatement with another.

**Invariant broken, and its replacement.** The release constrained the basis column to a vocabulary
and nothing more, which is how one value drifted into meaning "blank". Each basis is now a claim about
the record's own geography, and all four parts are enforced by `validation/invariants.py` against the
build's own output:

> `locality` is blank iff the basis is one of the three blank reasons;
> `duplicate_of_admin1_suppressed` implies a non-blank `admin1`;
> `no_admin1_deposited` implies a non-blank `country` and a blank `admin1`;
> `no_geography_deposited` implies both blank.

`country` and `admin1` are transport columns rather than projections, so this cannot live inside the
rule — no rule sees two columns at once, which is exactly why cross-column invariants get their own
module.

**This break is why declared deltas are counted per column rather than per field.** No `locality`
*value* changes: every blank stays blank and every non-blank was already right. The entire correction
is in `evidence_basis`. An earlier version of the parity gate compared only `final_value` for a
superseded field, so this correction would have registered as zero difference — and a genuine
regression in `source_field` or `manual_override` would have passed unnoticed alongside it. Every
provenance column is now declared for every superseded field, zeros included, so the *shape* of a
break is legible and a disagreement in an unexpected column fails.

**The row-set gap is down to eleven records, and it is pinned rather than absorbed.** The transport
carves on two closed predicates — the GenBank lineage names the `Enterovirus` genus, and the ledger
does not actively exclude the accession — plus R-MEMBERSHIP-AA-1, which recovers patent-division
deposits by capsid amino-acid distance. That reproduces 24,299 of the 24,301 shipped rows, and the
build's own carve is 24,308.

- Two shipped records it cannot reach: `E00765.1` and `E01571.1`, which land in
  R-MEMBERSHIP-AA-1's undecided 8–15% band. Both look like patent transcription artifacts — their
  same-patent siblings sit at 0.2–0.6% — but moving a published threshold to catch two records would
  be fitting the parameter to the answer, so they stay a declared gap awaiting a curator decision
  about the patent text. This replaces the earlier seventeen-record gap: R-MEMBERSHIP-AA-1 recovered
  fifteen of them, the sequence stage the curator's 2026-07-30 confirmation was waiting on.
- Nine records it carves that the release excludes. `AF326751.2` (Simian agent 5 strain B165) is the
  original: it carries `Enterovirus` in its lineage but ships as `non_ev_other` with no exclusion
  reason and no row in `registry/decisions.tsv`. The call is real; its basis is not in any declared
  input.

Both sets are declared in `derive/metadata.py` and compared for equality by the parity check, so a
record drifting in or out of the carve fails rather than being reported as a slightly larger gap.
The build never reads them — a transport that patched itself against a declared diff would pass
parity while proving nothing.

**Still not regenerated — `final/dictionaries/` and two audit views.** The list is down to six
files. `final/dictionaries/`'s four tables have no producer in this repository, and
`final/audit/record_disposition.tsv.gz` and `final/audit/sequence_evidence.tsv.gz` are 2.4.1 audit
views the new build writes no successor to — the second is the alignment layer's tier oracle, and
"The alignment layer's anchor" below records why it has no 4.0.0-native replacement and what checks
it instead. All six are carried with their hashes pinned in code
(`oracle/release.CARRIED_FINAL_FILES`, `tests/test_carried_files.py`), and every other file under
`final/` is now written by a verb in this repository.

### Inherited parse loss

Biopython's GenBank scanner silently discards text it cannot fit to the structured-comment
grammar, and the shipped release inherits it. Three records (MH484164.1, MH484165.1, MH484166.1)
lose their entire `##Assembly-Data-START##` block; two more (MN918613.1, PP461545.1) lose an
`##Assembly-Data-END##` continuation line with **no warning at all**, leaving PP461545.1's comment
ending mid-sentence. The parse emits exactly nine `BiopythonParserWarning`s, a count pinned by a
test so that a Biopython upgrade which changes what is dropped fails rather than quietly altering
shipped data.

Because parity is byte-exact, this loss cannot be corrected without deliberately breaking the gate
and cutting a new release. That is a real constraint, not an oversight.

### The one column not written: `sequence_scope`

`derive.metadata.PENDING_COLUMNS` holds exactly one entry, and that set shrinking from twelve to one
is the measure of what the derivation stages delivered. `assert_every_column_is_accounted_for` uses it
as the allowlist for a column blank on every row, so this is a *declared* absence — a column going
blank without an entry is a build failure.

It is not blocked on a missing stage. `derive/evidence.py` builds the Sabin 1/2/3 reference frame
from the frozen archive's own `mat_peptide` features and reproduces the shipped
`reference_region_coordinates.tsv` exactly. What does not follow is the column: fitted against every
threshold combination, coverage geometry against Sabin VP1 agrees with the shipped `sequence_scope` on
86.7% of poliovirus records, and the 13.3% are systematic rather than boundary errors — 745 records
the release calls `other_fragment` have a complete VP1, capsid or genome. So the shipped column is
not a function of Sabin-VP1 coverage alone, and a rule fitted to 86.7% would assert a wrong
determination on the remaining 13.3% — on the order of thirteen hundred records.

That is the same argument as the `virus_group` decline, applied to a column rather than a row set:
scoring well against the oracle is not evidence the rule is right when the disagreements have
structure. The column stays declared-pending until the determinant the release actually used is
known. It is the clearest single item for a metadata pass to close, because the measurement that
would settle it is already written — what is missing is the *definition*.

## The alignment layer

`final/alignments/` was carved in from a private pipeline until 2026-08-01. **It now holds this
repository's own alignments** — `evgc alignment-build` produces them from `final/canonical/`,
`final/source/` and the committed covariance-model core, using only `mafft` and Infernal's
`cmalign`, into `derived/alignments/`; promotion into the release is a separate, reviewed copy, the
same shape as `site/data/`. 2.4.1's nineteen files are retired to `releases/2.4.1/alignments/`,
where the declared delta is still measured against them.

**All six declared populations are built, at one parameter set, from the 4.0.0 canonical table.**
The previous state is what made that worth doing: five artifacts, `EV_unified` never built at all,
and two different gap-extension settings — `POLIO_unified` and `NPEV_unified` carried MAFFT
`--ep 0.5` while `PV1`/`PV2`/`PV3` predated it. Build times, one artifact at a time on eight
threads: PV3 7.4 min, PV1 13.5, PV2 24.9, POLIO 25.9, NPEV 74.5, EV 234.4.

The three anchored stacks are the strongest result. `PV1`/`PV2`/`PV3` come out at **zero sparse
columns and zero single-row columns**, at widths of exactly 7,441 / 7,439 / 7,432 — their own Sabin
genome lengths. Nothing enforces that; it falls out of the per-serotype covariance models being
`cmbuild --hand` against each serotype's reference, and it is the check that the anchored projection
is doing what it claims.

None of this is a parity claim on the shipped bytes, and it never can be: those bytes came from code
that no longer exists in that form, built at an unrecorded thread count with accidental
tie-breaking. What replaces parity is a **declared delta** — `evgc alignment-shape` states exactly
which accessions each rebuild adds and drops relative to the shipped file, with a reason per dropped
row from a closed vocabulary, and an *undeclared* drop raises rather than being absorbed. That is
the stronger claim: parity against artifacts built by vanished code would prove only that nobody has
touched the file since.

`evgc alignment-verify` is the acceptance gate. It re-reads the written artifacts and checks them
against populations derived independently from metadata — row set both directions, row order, block
widths summing to the row width, one declared alphabet, the coverage sidecar agreeing row for row,
the FASTA being a faithful projection of the Stockholm, and the cross-artifact set identities
(`EV == POLIO ∪ NPEV`, disjointness, each `PV{n}` inside POLIO). It is pure Python and needs no
aligner, so it runs on every push while a build takes hours. Every check ships with the mutation
that proves it fires.

**Two properties the anchored stack gets for free, and they are checked.** For `PV{1,2,3}` every
column is a real Sabin genome position, because the per-serotype covariance models are
`cmbuild --hand` against that serotype's own reference. So the three block widths sum to exactly the
reference genome length — 7,441 / 7,439 / 7,432, matching the shipped `n_sabin_reference_columns` —
the reference row projected onto its own frame equals its genome byte-for-byte, and `#=GC RF` *is*
that genome. Confirmed on real builds, not asserted.

**The rebuild reproduces upstream's own intermediate counts, which is the port-fidelity evidence
that does not depend on the shipped bytes.** Three independent agreements, none of them arranged:

- `POLIO_unified`'s `cmalign` populations come out at **2,036** sequences on the 5' side and
  **1,902** on the 3' — exactly the `population` figures recorded in the committed covariance
  models' own provenance, which were measured by the upstream build years earlier from a different
  codebase. The population filter is a rewrite, not a port, so agreeing to the record on both sides
  is evidence the filter means the same thing.
- **7** records are excluded from that 3' population as oversized, which is exactly the
  500–1,571 nt mis-segmented-CDS cluster upstream documented when it introduced the ceiling.
- The row-set deltas against the shipped artifacts land on the numbers the plan derived from
  metadata alone, before any alignment existed: **+98/−2** for `POLIO_unified`, **+715/−20** for
  `PV1_unified`, **+270/−2** for `PV3_unified`, with every dropped row attributed to a declared
  reason.

**Sequencing is per artifact; threading is per tool. Both were measured, and I had one backwards.**
A first build attempt fanned the six artifacts out concurrently, reached roughly 50 GB and froze the
machine. No single step is anywhere near that: pinned to one CPU, the MAFFT seed peaks at 0.10 GB,
`mafft --add` at 0.34 GB over 4,040 rows, `cmalign` at 0.57 GB, and the anchored pairwise projection
at 0.29 GB. So the fix was structural — `evgc alignment-build` has no `--parallel` option and builds
strictly one artifact at a time.

I then over-corrected and pinned one *thread*, which is a different axis and the wrong one. MAFFT's
`--addfragments` builds its guide tree with an all-to-all pairwise stage over the combined set; that
is the dominant cost of a large build, and it is threaded. On the real `POLIO_unified` pass-2 input
the difference is 97% CPU and 58 MB at one thread — still unfinished after 90 minutes — against 770%
CPU and 582 MB at eight. One thread bought no memory that mattered and gave up an eightfold speedup.
The default is now eight, a literal constant rather than `os.cpu_count()`, because the thread count
is recorded in provenance and a declared input should not depend on the host that built it.

**One measured regression in the 4.0.0 NPEV rebuild, and it is not tuned away here.** The CDS block
came out at 14,598 columns against the previous rebuild's 12,705 and 2.4.1's 7,677, on a row set
that grew by exactly one record. The extra width is not spread across the corpus — it is one
accession:

| | previous rebuild | 4.0.0 rebuild |
|---|---|---|
| rows | 14,217 | 14,218 |
| CDS columns | 12,705 | 14,598 |
| single-row columns | 3,258 | 5,205 |
| `PX242045` columns it alone occupies | **0** | **2,169** |
| `MG692415` | 1,980 | 2,022 |
| `MG692413` | 768 | 768 |

`PX242045` is an ordinary 7,327 nt Coxsackievirus A24 with 2,410 CVA24 siblings in the same
alignment, so 2,169 private columns — 30% of its own length — is a placement failure, not biology.
`MG692415` and `MG692413` were already like this and are unchanged; this is one record newly
shredded.

**`EV_unified` settles half the question at no extra cost.** It contains every `NPEV_unified` row
plus the 10,090 poliovirus records, built at the same parameters in the same run — and there
`PX242045` occupies **0** columns alone. The same record, the same settings, a superset of the same
corpus, placed correctly. So this is not an unalignable deposit: the NPEV placement is the artifact,
and a claim that the record is simply divergent would be false.

| | NPEV_unified | EV_unified |
|---|---|---|
| rows | 14,218 | 24,308 |
| CDS columns | 14,598 | 12,942 |
| single-row columns | 5,205 | 2,994 |
| `PX242045` private columns | 2,169 | **0** |
| `MG692415` | 2,022 | 1,926 |
| `AF326751` | 0 | 48 |

**What remains a hypothesis is the trigger.** `PX242045` and the one newly-added record
`AF326751.2` are both *addons* (`enterovirus_type_sequence_confident=FALSE`), and addons are placed
in one shared MAFFT `--addfragments` call where fragments interact — so a divergent addon displacing
another is the obvious reading. Confirming *that* costs one 75-minute NPEV rebuild with
`AF326751.2` withheld, which has not been run. What is established is narrower and still useful:
addon placement is a property of the addon *set*, not of the record, and `NPEV_unified` is the
artifact where it went wrong.

Nothing was tuned to make the number smaller. `--ep 0.5`, `--op 4.5` and `--lop -24.0` are the
measured settings recorded in `parameter_departures`, and reaching for them to flatten a single
record's placement would be fitting a global parameter to one accession. The shape report counts
single-row columns and names their owners on every build precisely so this is visible without
anyone going looking.

**What the rebuild is honest about.** The NCR blocks keep only `cmalign` match columns, so
insert-column residues are discarded; the anchored CDS projection drops insertions relative to the
reference for the same reason a fixed reference frame must. Both are lossy by construction and both
are reported in the shape report's residue-occupancy distribution rather than hidden. A record with
no placeable material still gets a row — all gaps, with the reason recorded per block in
`<name>.coverage.tsv.gz` — so the row set stays literally 1-to-1 with metadata and "block absent"
stays distinguishable from "deleted" without inventing an alignment character.

**2.4.1's alignments were not 1-to-1 with the release they shipped beside; 4.0.0's are, by
construction.** The delta each artifact declares against `releases/2.4.1/alignments/`, as built:

| artifact | 2.4.1 rows | 4.0.0 rows | delta |
|---|---|---|---|
| `POLIO_unified` | 9,988 | 10,090 | +106 / −4 |
| `NPEV_unified` | 14,050 | 14,218 | +168 / −0 |
| `EV_unified` | 24,038 | 24,308 | +272 / −2 |
| `PV1_unified` | 3,732 | 4,337 | +717 / −112 |
| `PV2_unified` | 3,604 | 3,790 | +357 / −171 |
| `PV3_unified` | 1,425 | 1,597 | +263 / −91 |

Every dropped row carries a reason from a closed vocabulary, and an *undeclared* drop raises rather
than being absorbed. Across the three serotype files the 374 drops are 332 `virus_type_lost`, 37
`serotype_relabelled`, 3 `carve_excluded` and 2 `group_moved`.

`evgc alignment-population` derives the row set: upstream tied *membership* to evidence confidence
(a record its typing could not resolve confidently was simply absent), and the rebuild ties
membership to curated `virus_group`/`virus_type` instead, using evidence only to assign the
seed/backbone/addon tier. That inversion is why the serotype files both grow and shrink — they
admit fragments upstream's evidence gate excluded, and they decline records upstream typed from
curated data that R-TYPE-2 will not type from an organism name stating no serotype. It is also why
PV1's P1 coverage is 3,623 of 4,337 rather than all of them: a deposit named "Poliovirus 1" now
joins PV1 with or without a capsid, and the 714 rows without P1 are almost exactly the 717 the
population added. The `serotype_relabelled` drops were adjudicated 2026-07-30 — 40 of the 43
relabelled records have fewer than 100 capsid codons compared (mean 58.3), so the coverage-guarded
serotype rule correctly rejects the sequence-based capsid call and falls back to the submitted
GenBank name.

Applied to 2.4.1's own row sets, this repository's tiering columns still reproduce its tier splits
exactly — `POLIO_unified` 8,736/1,252 and `NPEV_unified` 10,418/3,632 — the strongest port-fidelity
evidence available without running an aligner, since it needs no aligner at all. That claim is
about the evidence table and those row sets, neither of which the re-anchor moved, which is why it
survived it unchanged.

**The native toolchain is pinned twice, from independent sources.** `pixi.toml` declares two
environments: `align` (Python 3.12, `mafft` 7.526, Infernal 1.1.5, both `linux-64` and `osx-arm64`)
and `seed` (`osx-arm64` only; adds `viennarna` 2.7.2 and hands `mafft-xinsi`/`RNAalifold`/`cmbuild`
to a child process when a covariance model is rebuilt). They are not in one solve group on purpose:
`viennarna` is a `py313` build, and a single solve would drag the project interpreter from 3.12 to
3.13 and re-resolve `biopython`/`duckdb` against a version the parity gate has never run on.
`registry/toolchain.json` records each tool's resolved `(version, build)` per platform;
`evgc alignment-toolchain` re-derives it statically from `conda-meta/` and dynamically from each
binary's own self-report, and refuses on any disagreement — either source alone is satisfiable by a
lie, together they are not.

**The NCR covariance-model core is committed, not rebuilt.** `mafft-xinsi` does not work from a bare
bioconda install — bioconda's `mafft` package omits the `mxscarnamod` helper binary — so building a
genus-wide covariance model from scratch additionally needs a compiler and a network fetch
(`scripts/setup_mxscarna.sh`, pinned by sha256, not expected to run even on a fresh clone). Per
Mike's decision, the ten models the NCR structural block needs — four genus-wide, anchor-free
models (`POLIO`/`NPEV` × 5′/3′) and six per-serotype, Sabin-anchored models (`PV1`/`PV2`/`PV3` ×
5′/3′, built `cmbuild --hand` against each serotype's own Sabin reference genome coordinates) — are
committed as inputs-of-record under `registry/alignment_seeds/` instead, so a routine build needs
only `mafft` + Infernal's `cmalign`. `evgc alignment-verify-seeds` re-hashes them and cross-checks
each model's match-column count against its recorded provenance, with no native toolchain required.
`EV_unified` builds no covariance model of its own; it reuses `NPEV_unified`'s, matching the shipped
`EV_unified.provenance.json`'s `cm_reused` field.

**Running `mafft`/`cmalign` needs a second, weaker guard, by design.** `sandbox.ESCAPE_EVENTS`
refuses every way of starting a child process, on the stated grounds that a child is unguarded and
could read anything — which means the alignment stage genuinely cannot run under
`install_input_guard`. `sandbox_exec.install_tool_guard` is the honest resolution: a second,
differently-named mechanism, sharing every path decision with the first guard via
`sandbox._path_rule_set` (so `final/`, `raw/` and `registry/legacy/` stay exactly as protected),
but permitting exactly one call shape — the single `subprocess.run` `align.runner.run_tool` makes —
inside a one-shot armed window, with an exact-key child environment, a scratch-only cwd, a
basename-only argv, and a resolved-binary allowlist. Its own module docstring carries a full
"what this does and does not prove" account in the same voice as this section's; the headline
limit is the same one this guard has always had for children: the child itself is starved, not
audited, once it starts.

One design correction is worth recording because it was found by measuring, not by reading code.
An earlier draft keyed the binary allowlist on the `_posixsubprocess.fork_exec` audit event, which
carries the fully `PATH`-resolved candidate list — verified against CPython 3.14. Run against
CPython **3.12.13**, the version this repository is actually pinned to, that event **never fires**
for a `subprocess.run` call. Had that shipped, the allowlist check it depended on would have never
executed on the one interpreter this repository uses, passing every test written against 3.14 while
doing nothing in production. The fix resolves the executable against `PATH` in Python instead,
inside the one event (`subprocess.Popen`) that both versions do raise.

A second gap, also found only by running the falsification battery rather than by reading the
guard's own code: an early version of the hook had no branch for the `open` event at all, so a
plain `Path.write_text()` into `final/` or `Path.read_bytes()` from `registry/legacy/` passed
silently — those never go through `MUTATION_EVENTS`, only through `open`. Two tests that planted
exactly those two calls caught it before anything else did.

**Byte parity with the shipped alignments is not a goal, and is not achievable even by porting
upstream's code unchanged.** Upstream's own history records a gap-parameter change (`--lop -24`,
adopted to stop short addon fragments being shredded) that landed in code but was never used to
regenerate the shipped artifacts — the shipped provenance still carries the pre-change parameters.
So the shipped bytes were produced by code that no longer exists in that form; reproducing them
would mean reproducing a bug, not a build. Acceptance for a future alignment build is population
correspondence, internal invariants (the amino-acid-to-codon backtranslate invariant, zero CDS
residue loss, Sabin-row recovery), and a human-reviewed shape report — not a hash match against
`final/alignments/`.

### The alignment layer's anchor

**Closed on 2026-08-01, except for one input, and that exception is measured rather than deferred.**

The layer used to read the frozen 2.4.1 release under `final/` because the stages producing its
inputs natively did not exist. They do, and `final/` now holds their output, so `align/` reads the
release this pipeline builds without a single path changing — every one was already declared once,
in `oracle.parity`, and the tree under them moved. What follows is what that cost and what it
bought, point by point against the six the previous version of this section left open.

**1. The tier predicate still has no native producer, and now says so out loud.**
`align/population.py` splits each population into backbone and addon using
`serotype_sequence_confident` and `enterovirus_type_sequence_confident` from
`final/audit/sequence_evidence.tsv.gz`, and `derive/evidence.py` writes a deliberately narrower
schema with no successor to either column. Two native candidates were measured before being
rejected: annotated-CDS presence reproduces the shipped tiers on 88.1% of poliovirus records and
78.7% of non-polio, and an ORF-length floor does no better at any threshold (best: 90.4% and 76.1%).
A rule scoring 90% here would be the 98.3% mistake this document already records, in a different
column. So the table stays carried — but `population.assert_evidence_covers_the_carve` now requires
its coverage gap against the carve to be *exactly* the two residual sets `derive/metadata.py`
already declares, in both directions. Before that check, nine carved records had no evidence row and
took `addon` by default, with nothing anywhere saying they had.

**2. The six `expected_rows` tripwires are re-derived against 4.0.0.** EV 24,301 -> 24,308,
POLIO 10,084 -> 10,090, NPEV 14,217 -> 14,218, and the serotype files 4,427/3,939/1,693 ->
4,337/3,790/1,597. The serotype drop is the consequential one and it is a typing change, not a
membership change: 366 poliovirus records now carry a blank `virus_type` against 25 before, because
R-TYPE-2 reads the organism name and declines where the name states no serotype. They are members of
`POLIO_unified` and `EV_unified` and of no `PV{n}` file. 92 of the 366 are >=3,000 nt, so this is
not a fragment artifact — a full-length deposit that names no serotype is one this pipeline will not
type.

**3. The blank `virus_group` that would have made a repoint unsafe is gone.** `population.tier_of`
raises on the first record whose group is neither value, and `select()` would have silently dropped
1,385 of them — the one failure mode in the list that was not loud. The partition projection closed
all 1,385 before the repoint, and `UNRESOLVED_PARTITION_ROWS` is now a named zero precisely so this
cannot come back quietly: a decline there is not a blank cell, it is a broken alignment layer.

**4. The missing inputs are not missing.** `final/` carries `source/normalized_tsv/`,
`audit/record_disposition.tsv.gz` and `audit/sequence_evidence.tsv.gz` — the first because the
source layer never moved, the other two because they are deliberately carried for exactly the two
consumers that still need them (`align/shape.py` and the tier predicate above).

**5. `final/alignments/` ships the pipeline's own alignments**, and the manifest hole that would
have made that unmanifested is closed: `export/release.py` declares `BUILD_ARTIFACT_RELATIVES`
rather than `rglob`-ing its destination, which would have hashed the carried source and alignment
layers into a manifest claiming they were the metadata build's output. The alignment artifacts are
covered by `CARRIED_FINAL_FILES` with hashes pinned in `tests/test_carried_files.py` — carried in
the mechanical sense that `build-metadata` does not write them, not in the provenance sense: they
come from `evgc alignment-build` in this repository, and their pins move when a rebuild is promoted,
which is a reviewed act rather than a data edit.

**6. The write/read asymmetry is resolved by there being one release.** `final/` left
`sandbox.IMMUTABLE_DIRS` and stayed in `READ_REFUSED_DIRS`, which was always the half that carried
the property: a build that reads the previous canonical table can reproduce it perfectly and prove
nothing. Writing is a different act. The refusal is now "a file the build did not write in this
run", so the manifest writer and `export/metadata.py`'s read-back checks work while an
undeclared read of the previous release still fails — including of `.DS_Store`, which is how the
first attempt was caught.

And the sentence that motivated the whole exercise no longer holds: **this repository held two
canonical tables that disagreed, and now holds one.** `align/contract.py`'s membership note
("Curator decision, settled 2026-07-30 — do not re-litigate") settles against that one.

## The undeclared-input guard

Self-containment is enforced at runtime, not documented and hoped for. `evgc build-source` and
`evgc parity-source` accept `--guard-inputs`, which installs a `sys.addaudithook` that fails the
build on the first undeclared access. CI runs the real 25,727-record parity build under it on every
push.

This exists because the pipeline being replaced read `~/Downloads/*.xlsx` and a sibling repository by
absolute path for two of its stages, and nobody noticed until those files had been deleted. A prose
rule would not have caught it; a failing build would have.

**What it proves.** Within the guarded process, the build performed no read outside the clone, the
scratch directory, and the interpreter's own installation; **no read of `final/` at all**; no read of
the frozen [`registry/legacy/`](../registry/legacy/) tree; no write or filesystem mutation touching
`final/` or `raw/`; no write outside the clone and scratch; no network call; and no child process by
any of `subprocess`, `os.system`, `os.spawn*`, `os.exec*`, `os.posix_spawn` or a bare `os.fork`. It
raises *and* records every violation, and `assert_no_violations()` re-checks the record after the
build, so a caller that swallowed the exception in a bare `except` still fails. Paths are resolved
before the allowlist decision, so a symlink sitting inside an allowed root cannot alias something
outside one.

The `final/` read refusal is new, and it changed how the `parity-*` verbs run. Refusing only *writes*
left the failure that matters wide open: a derive stage that reads the shipped canonical table can
reproduce it perfectly and prove nothing, and reaching for that read is exactly what happens while
someone calibrates a rule against the oracle. The comparison itself must read `final/`, so
`--guard-inputs` on `evgc parity-source` and `evgc check-declines` runs the **build in a guarded
child process** and compares in the unguarded parent, and it fails unless that child reported the
guard's own PASS line. Before this, the guard was installed in the same process that then read the
release, which made it structurally unable to distinguish a build reading the comparison target from
the comparison itself.

The reproducible evidence for all of that is `tests/test_sandbox.py`: every rule in the event tables
has a test that fails when the rule is removed, and positive controls assert legitimate work still
succeeds so that a guard which refused everything could not pass. Deliberately planted mutations
were also run by hand — a neutered containment check, a dropped violation record, an unguarded
socket, an unguarded subprocess, an added read root, a forced-false write intent, an emptied
`FROZEN_DIRS` and an emptied `MUTATION_EVENTS`, all caught — but that battery is a record of an
exercise, not a runnable artifact, and should not be cited as the check.

The scope above is narrower than what this section claimed before 2026-07-29, in the direction of
being true. A review demonstrated live bypasses of two of the guarantees as then written, and the
event tables in `sandbox.py` were extended to cover them: `os.system` and `os.spawnl` ran children
the guard never saw, and every filesystem mutation that does not pass through `open` —
`os.remove`, `os.rename`, `os.replace`, `os.mkdir`, `os.truncate`, `os.symlink`, `shutil.rmtree` —
was invisible, so `os.replace(tmp, final/canonical/...)` could rewrite the immutable release under a
clean `PASS`. Each is now refused and has a falsification test, alongside a negative control that
mutating scratch is still allowed. `os.fork` is what actually closes the child-process family: on
POSIX `os.spawnl` is fork+exec in Python and raises only that event, which was established
empirically rather than read off the audit-event table, whose documented `os.spawn` event does not
fire on this platform.

**What it does not prove.** Five limits worth stating plainly:

- **The allowlist is not just the clone.** `site-packages`, the stdlib, DuckDB's bundled extensions,
  Biopython's data files, `$TMPDIR` and a fixed list of system paths are permitted, because a guard
  that fired on `import` would test nothing. The home directory and sibling repositories are *not*
  permitted, which is the property actually under test. One consequence: if a user site-packages
  directory under `$HOME` is on `sys.path`, it is allowlisted along with the rest of `sys.path`.
- **Reads are audited through the `open` event only.** A C extension calling `fopen()` directly does
  not raise it and would not be seen. Child processes are *blocked* rather than guarded, for exactly
  this reason — an unguarded child could read anything.
- **The stat family is a genuine hole.** `os.stat`, `Path.exists()`, `os.listdir` and `os.scandir`
  raise no event this hook subscribes to, so a build can probe for undeclared paths undetected. It
  cannot *read* them, which is the property that matters for parity, but "did this file exist" is
  observable. This is pinned by a test that asserts the hole, so if it ever closes the limits get
  revisited rather than silently going stale.
- **Hardlinks are not covered.** The path checks resolve symlinks, so aliasing through one is caught,
  but a hardlink is a second directory entry for the same inode rather than a path that resolves
  elsewhere. `os.link(final/audit/x, $TMPDIR/h)` followed by `open($TMPDIR/h)` is not seen. Closing
  it would mean comparing `(st_dev, st_ino)` on every access, which is disproportionate to the
  threat model here: this guard exists to catch a build that accidentally depends on an undeclared
  file, not to contain an adversary.
- **It says nothing about determinism or correctness.** Access scope only. Byte-stability is a
  separate test, and parity against the release is a separate gate.
- **It cannot show the declared inputs are sufficient.** It detects touching something undeclared,
  not depending on something absent. A build can be fully self-contained and still wrong.

The general lesson is the one this repository keeps relearning: a guarantee stated in prose and a
guarantee implemented in an event table drift apart silently, and the prose is always the optimistic
one. The tables in `sandbox.py` are the specification; this section summarises them.

Audit hooks cannot be uninstalled, so a guarded build must be its own process; every guard test runs
under `subprocess` for that reason.

## Frozen baseline

`releases/2.4.1/parity.json` records the public release commit, source build commit, raw archive
identity, row counts, and authoritative release hashes used by the rewrite. The baseline is a test
oracle only. (`releases/2.1.5/parity.json` and `releases/2.3.0/parity.json` are retained as
historical records of retired baselines, no longer verified against the tree.)

The oracle is itself checked. `evgc validate-contracts` re-derives every claim in the contract from
the shipped release on each CI run: file-byte hashes are recomputed, `logical_content` hashes are
cross-checked against `final/audit/release_file_manifest.tsv`, row counts (including the
vouched/provisional split, which is recounted from `curation_status` rather than inferred by
subtraction) are recounted, the frozen archive's declared member is authenticated by name, size,
and uncompressed hash, and `final/audit/build_manifest.json` must agree with the contract's source
commit, schema version, and raw-snapshot hash. Editing the contract to make a future build pass
therefore fails immediately, because the contract would no longer describe the release it is
pinned to.

`public_release_commit` is the one field that is documentary rather than verified: it names the
commit at which this repository first published the release, which a later checkout cannot confirm
from its own contents.

Passing parity means at minimum:

- identical source and canonical record identity;
- identical vouched/provisional partitions;
- identical FASTA identifiers and nucleotide sequences;
- migration of all 2,912 human decisions the release shipped, and 28 deterministic rules. The ledger
  now holds 3,168 — 2,975 `active`, 183 `retired`, 10 `superseded` — and the difference is approved
  curation history rather than a parity failure, itemised by `source_artifact`. The largest single
  block is the 243-row locked VDPV/wild reconciliation allowlist, migrated 2026-07-30: the last input
  to `poliovirus_classification` with no counterpart here, and every row already agrees with the
  shipped column, which a test asserts. The `superseded` rows are carried-forward assertions (the
  `engineered_or_construct=FALSE` D2 rows, plus curator revisions to `AB180070-73` and `JC013129`)
  that a from-scratch regeneration would otherwise have dropped silently. See
  [`registry/README.md`](../registry/README.md);
- equivalent normalized source and canonical scientific values;
- complete, referentially closed provenance;
- deterministic repeated builds from declared inputs.

Compressed file bytes are required to match when deterministic compression is part of the format
contract. The DuckDB convenience database is compared by logical content, not file bytes.

## Completion criterion

The README reproducibility claim changes only after a fresh clone builds and validates the complete
release without undeclared files, network access, private repositories, or existing `final/`
artifacts. That transition requires a new release version; the current baseline release remains
unchanged in the meantime, exactly as 2.1.5 and 2.3.0 did before it.

### Every decision now has a stated outcome

D2 was not a bug in a rule. An assertion sat in `registry/decisions.tsv` for two releases while the
pipeline recomputed the value from scratch, and nobody noticed — because nothing anywhere said what
had become of it. `evgc build-metadata` now writes `audit/decision_applications.tsv.gz`, one row per
decision per canonical field it can reach, and **a decision with no row is a build failure** rather
than an absence.

The measured tally, 3,190 application rows over the 3,168-row ledger (`release/3.2.0/audit/
decision_applications.tsv.gz`):

| status | n | what it means |
|---|---|---|
| `applied_filled_unresolved` | 2,640 | the decision is the only reason the cell has a value |
| `not_in_force_retired` / `_superseded` | 183 / 10 | the curator took it back |
| `applied_exclusion` | 173 | the record is absent from the carve *because* the ledger says so |
| `no_canonical_field` | 123 | reference-selection curation the canonical schema has no column for |
| `applied_changed` | 31 | in force, and the value differs from the rule's |
| `applied_unchanged` | 24 | **a rule now reaches the same value on its own** |
| `subject_outside_carve` | 6 | no canonical value exists to change |

**`field_not_projected` is gone.** It held 2,553 rows when this table was first measured — decisions
whose field had no rule to reach it. Every one of those fields is now projected, so the bucket is
empty and the status is a guard against regression rather than a description of the present. That is
the single clearest measure of what the derivation stages added: the same ledger, and nothing in it
still waiting for a rule.

Two other rows are worth dwelling on. **`applied_unchanged` is a finding, not bookkeeping**: 24
assertions the rules would now make anyway, which makes them candidates for retirement rather than
curation doing work — the opposite of the D2 problem and only visible because the status exists.
And `applied_exclusion` **verifies** the absence rather than trusting it: an active exclusion whose
record is still in the carve fails the build.

Distinguishing `applied_changed` from `applied_unchanged` requires a counterfactual, so every field is
projected twice — once with the ledger and once with it withheld. There is no way to tell from the
final value alone whether a decision changed anything, and asserting that it did without checking is
how D2 happened.

Closes backlog **B27**: `REGISTRY_FIELD_TO_CANONICAL` is the join between a ledger `field_name` and
the canonical fields it reaches, and a field missing from it is a build failure rather than a silent
default.

## What a code review changed, 2026-07-30

An independent review of the increments above found twelve issues. Five mattered enough to change
behaviour, and they are recorded here because each one is a class of mistake this repository claims to
defend against.

**`evgc parity-metadata --guard-inputs` had never worked.** The reader required the release's nine
provenance columns while the writer wrote ten, so the guarded path raised on every invocation. The
unguarded path keeps its rows in memory and never reads the artifact back, so neither the corpus test
nor CI could see it. The claim that the verb runs its build in a guarded child was therefore half
unexecuted and half broken. Fixed, and `test_the_guarded_parity_verb_actually_runs` now shells out to
it — the only way to cover it, since an audit hook cannot be uninstalled from the testing process.

**The partition rule was guessing on 99 records.** `Human enterovirus` — the pre-2016 ICTV name of the
polio-containing species, unqualified — was absent from `UNINFORMATIVE_ORGANISMS`, so 95 records
carrying it fell through to `non_polio_enterovirus`, along with four named for a strain rather than a
type. One of the 95 ships as `EV-C96`, inside that very species. Every one of the 99 happens to ship
`non_polio_enterovirus`, so the rule scored 100% on the group and parity agreed: the top declared risk,
realized in the same commit whose docstring warns against sizing an ambiguity by its disagreements.
The declined population was **1,832** after the fix, not 1,733. (It is 1,596 today; curated-
classification entailment resolved part of the group afterwards. The number above is what the review
measured, kept as written because this section records what changed on that date.)

**A declared delta could be satisfied by a substituted record.** Comparing per-column *counts* let one
record be fixed while another regressed, keeping the total identical and the gate green — demonstrated,
not theorised. `SUPERSEDED_FIELD_WITNESSES` now declares a hash of the disagreeing set itself, per
column, so any substitution fails. Columns whose count already equals every compared row need no hash,
because "all of them" is already an identity.

**The cross-column invariants were enforced by nothing.** Replacing both with no-ops left `pytest`,
`pytest -m slow`, `validate-contracts` and the then-current `parity-metadata` all green — so the claim that they are
enforced was prose, which is R2 in the file that describes R2. `tests/test_invariants.py` now supplies
a negative control per property plus positive controls. Two real holes went with it: a locality row
whose transport row was missing skipped all four checks rather than failing, and either invariant
passed vacuously on an empty input.

**Two rules ignored the ledger.** `specimen_type` never consulted `view.decisions`, so seven active
assertions were silently overridden — inside the mechanism built to prevent exactly that. And
`_membership` compared `is_poliovirus` against `"TRUE"`/`"FALSE"` and fell through on anything else, so
a decision filed as Python's `True` would validate, be ignored, and reappear in the curation queue with
no error anywhere. Both fixed; the malformed value now fails the build.

Also corrected: the curation queue advised a *rule change* for ~10,000 records that deposited no
`/isolation_source` at all, where no pattern can ever help; an unparseable date was reported as "no
date deposited", the same false determination the date break had just corrected; `water` and `blood`
matched inside "watery" and "bloody" in patterns the commit fixing `fec`-in-`infection` left unanchored;
`coverage_by_field` was dead; and seven of eight `REGISTRY_FIELD_FOR_CANONICAL` entries were
unreachable, one of them structurally so.
