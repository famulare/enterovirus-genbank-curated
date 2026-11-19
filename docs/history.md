# How this dataset was made

A short history of how this dataset was built, April to November 2026. It covers:

- what data was chosen;
- how curation worked;
- how the work was split between Mike and AI agents;
- where Mike's sign-off came quickly or slowly;
- what was reasoned through, and who brought what;
- how the shipped product was decided.

The first three months of work happened in a prior private repo. This repo was carved out of it on 2026-07-29 and rebuilt from there. All dates are 2026.

## Timeline

| Dates | Where | What happened |
|---|---|---|
| 04-30 → 05-08 | prior private repo | The GenBank dataset starts as reference data for other work. The GenBank query runs on 05-07 and returns 25,727 records. First extraction, review queues, VP1-only output. |
| 05-28 → 06-01 | prior private repo | Curation rebuilt as rules plus locked allowlists, with a three-layer schema. Scope widened from VP1 to whole genomes. The sequence classification pipeline is built and run unattended over a weekend. |
| 06-24 → 06-27 | prior private repo | Membership rule locked; poliovirus / other-enterovirus partition added. v1.0 ships 06-26. Codon-aware alignment rebuild. |
| 06-27 → 07-21 | — | About three weeks with no work. |
| 07-21 → 07-26 | prior private repo | Unresolved records closed out. Enterovirus typing panel built. A paper-based review moves 1,518 records from `VDPV` to `cVDPV` or `iVDPV`. Whole-genome all-poliovirus and all-enterovirus alignments are built overnight. Audit of the final datasets. |
| 07-27 → 07-29 | prior private repo | Visual review campaign over the final data. Release schema goes 2.1.0 → 2.1.5 under external review. This repo is carved out on 07-29. |
| 07-29 → 08-01 | this repo | Contracts and a parity oracle. Pipeline rewritten in stages. Alignment pipeline ported. Explorer website built. Releases 3.0.0 (07-31, the first built from `raw/` and `registry/` alone), then 4.0.0 and 4.1.0 (08-01). Meanwhile the prior repo kept fixing data through 2.4.1, and this repo re-imported each version. |
| 08-10 → 08-18 | this repo | Post-sprint review. 5.0.0 (08-16) retires the 2.4.1 inheritance. Curator rulings, alignment indel repairs R1–R6, explorer alignment raster. |
| 09-05 → 11-09 | this repo | Maintenance: analytics on the explorer, and retiring a weekly alignment build that had never completed a run. |
| 11-17 | this repo | Release 5.1.0, a curation-only correction: the half of a 2026-07-30 ruling that had never reached the data. Ten records gain a classification the vocabulary had carried, unused, since the ruling. |
| 11-17 | this repo | Release 5.2.0, two cells. Reading a 2026-07-31 reason closely showed it had ruled out the wrong alternatives and never decided the question; a sequence measurement settled it. The first release to move a value a consumer had already read since 4.1.0. |
| 11-18 | this repo | Release 5.3.0, the two records 5.2.0 held back. The curator ruled them poliovirus on the deposit's own definition line. That moves them across the partition, so `POLIO_unified`, `NPEV_unified` and `EV_unified` were rebuilt, about five and a half hours serial. The first release since 2.4.1 where the partition differs from the baseline, on two records. |

## 1. Data choice

**Source.** NCBI GenBank Nucleotide was queried on 05-07 with poliovirus organism terms plus "polio" free-text terms, returning 25,727 records ([`raw/genbank_query.md`](../raw/genbank_query.md)).
- The download is frozen in `raw/` and authenticated by `raw/raw_manifest.json`.
- It has changed twice: the initial release and a manifest path fix.

**Membership comes from metadata names, not from a sequence band.**
- Poliovirus has been notifiable for decades, so a GenBank poliovirus organism call is very likely correct.
- A sequence check catches records the names miss, mainly patent deposits. The check is capsid amino-acid distance to Sabin.

**The non-polio set is what a poliovirus query returns.**
- NCBI's translation of the query adds `"Enterovirus C"[Organism]`.
- That pulls in 16,055 records whose names don't mention poliovirus (backlog B35).
- So the non-polio records were never designed as a sample of non-polio enteroviruses.

**Scope changed three times:**
1. **VP1 → whole genome (05-29).** The first output was VP1 only.
   - The new rule: align whole genomes in the Sabin reference frame, and treat VP1 coverage as a later view.
   - Length rules followed. There is a 50 nt fragment floor and a 7,700 nt hard cap; the longest real poliovirus record is 7,506 nt.
2. **Poliovirus only → two partitions (06-24).** The non-polio records became a second deliverable, shipped as-is rather than vouched.
3. **Per-serotype → genus-wide alignments (07-25).**
   - 1,326 poliovirus records have no capsid, and so no Sabin frame.
   - An all-poliovirus alignment gave 1,230 of them a place.
   - Nothing was filtered out for being of little use: "filtering for utility is a choice i want to leave for db users, not me here."

**Today: 24,305 records.**
- 10,089 poliovirus records are `vouched`: Mike has reviewed them directly, on the explorer and against the literature.
- 14,216 non-polio records are `provisional`: that review hasn't happened yet.
- The two labels line up with the partition only because the review has covered poliovirus and nothing else.

## 2. Curation strategy

**The core pattern was set in the first week and hasn't changed.**
- A deterministic rule decides the common case and surfaces candidates.
- A small human-curated allowlist locks the exceptions.
- Mike's framing on 05-28: "joint human-llm reasoning to codifying fully reproducible code logic".

**Principles set in the prior repo:**
- **Three layers per curated field:** the raw GenBank value, a reviewed override, and the consumer column. The shipping rule (06-26): "ship all pure data, ship one cleaned canonical variable per state that has complex decision logic".
- **Two passes.**
  - The first pass is conservative: `unresolved` beats a fabricated value.
  - The second pass works through the problem set as explicit exceptions.
- **Classification authority is split.**
  - Sequence decides the tiers it can measure: Sabin-like, VDPV and wild, using GPLN divergence thresholds.
  - Text and papers own what a sequence cannot carry. `iVDPV` is a property of the host; `cVDPV` is a property of a transmission chain.
  - The 07-24 paper-based review moved 1,518 records out of `VDPV`. Mike later called these "hard-won, paper based judgements" that had to survive the rewrite.

**This repo's rewrite turned those principles into structure:**
- **The ledger.** [`registry/decisions.tsv`](../registry/decisions.tsv) holds every human assertion, and nothing else may.
  - Decision ids are content hashes.
  - Rows are superseded or retired, never deleted.
  - Today it has 4,939 rows, 4,722 of them active.
- **The rules.** [`registry/rules.json`](../registry/rules.json) holds 39 deterministic rules, with their thresholds as data.
- **Every applied decision reports its outcome**, and a missing outcome fails the build.
  - This came from a decision that was recorded but never applied.
  - The lesson: "curation has to land where it is applied, not only where it is recorded" (e0653bc).
- **Rules decline rather than guess.** Declined cells become a curation queue, grouped by the input that was missing. 25,051 declined cells reduce to 268 questions.
- **Deliberate breaks from the inherited release** are allowed when they replace a weak guarantee with an enforced one. Each break is pinned. Examples: date precision, the basis for locality, the host field, and `engineered_or_construct`.
- **Coarsening is not conservative.** "A coarsened value is a lost judgement" ([`classification-migration-gap.md`](classification-migration-gap.md)). By 4.0.0, every remaining classification difference from 2.4.1 was categorized, and 97.8% agreed.
- **Curation, not science.** When a question turned into a scientific claim, Mike kept the existing label: "trending into science not just curation" (08-17).

**`engineered_or_construct` shows how a definition had to be rebuilt.**
- The inherited predicate matched `\bPAT\b` in a text blob, so all 506 patent records shipped TRUE.
- On 07-29 Mike redefined it: "Engineered means someone assembled that specific genotype for some purpose and it is not a genotype that occurred in nature." About 500 records flipped to FALSE.
- DQ205099 then went TRUE → FALSE → TRUE. That exposed the gap: every sequence-based check answers "is this sequence engineered?", and none answers "is this material a construct?" (4b2fb32).

## 3. Working with agents

Agents did most of the code and data work. Claude Opus ran most sessions, with Sonnet and Haiku on some. A model from another provider wrote some of the earliest commits and later reviewed release candidates. Mike set direction, made the scientific calls, and checked results. These methods held up:

- **State lives on disk, not in an agent's context.**
  - Roadmaps, decision logs, design contracts, worklogs and decisions-needed files.
  - When an agent's context degraded, a fresh agent took over from a handoff prompt that named the repo docs as ground truth.
- **Decision routing.**
  - Agents decide mechanical and reversible things and log them.
  - Load-bearing calls come back to Mike with a recommendation, as numbered questions.
  - Silence means assent: "lack of comment implies my assent" (05-28).
  - An unattended agent facing uncertainty should "act in a way that preserves the discomfort for me to see on Monday" (05-30).
- **Parallel agents.** Several sessions often ran against the same checkout, some in worktrees, and Mike relayed collisions between them by hand. That sped things up, but cost cleanup: stray builds, other agents' commits swept up, and an unmerged branch nearly deleted.
- **Unattended runs.** Long alignment builds ran overnight. Eventually they were gated on the machine being idle rather than on a timer.
- **Independent review.**
  - Each of the four rounds of external review on the 2.1.5 release found a validation that could not fail.
  - On 07-29 Mike named the cause: "these task lists have been longer than the coherence time you can maintain".
  - After that, adversarial review was standing practice. The 07-29 sweep in this repo used four independent Opus reviewers and found about 59 defects.
  - Single-reviewer recall was low, and fixing introduced close to one new defect per fix ([`review-backlog.md`](review-backlog.md)).
  - The result was a working agreement: no guarantee without a test that fails, and nothing an agent writes is certified by that agent.
- **Oracles that agents cannot game.**
  - Parity contracts recompute hashes from the bytes.
  - The build cannot read `final/`, so a rule cannot copy the answer it is being checked against.
  - The baseline release is a code constant, so retargeting it is a visible code change.
- **Rules that came from specific catches:**
  - "never fix on site. only ever fix at source and regen" (07-29).
  - Research a regression before reporting it, and decide whether the new number is more correct (08-17).
  - Document any invariant you break, with the new one in place.
  - No re-adjudicating settled rules late in a release.
  - Don't relitigate parameter defaults.
- **The expert is the detector.** Agents were good at checking internal consistency. Most real data errors were found by plots Mike asked for and read himself.
  - A dN/dS scatter showed 154 records labelled VDPV sitting in the wild cluster (07-27).
  - A screen on the explorer's synonymous capsid distance found 20 wrong `wild` labels that came from a paper-title match (08-16, e506147).
- **Trust widened in steps.**
  - Merge rights for `site/` once the design settled: "we're past the crux of design" (07-30).
  - Autonomy, with conditions, for the release sprint.
  - From 08-10, report first, then plan, then itemized approval.
- **Infrastructure friction was constant.** Context limits, compaction, network drops, and safety filters interrupting sessions on poliovirus material. The recovery was always the same: start a fresh session from a handoff.

## 4. Where sign-off was hard and where it was easy

Mike's sign-off rarely appears as stated approval. It shows up as the focus of work moving on and not coming back. So difficulty here is measured by how often a topic was reopened after the focus first left it.

**Hard:**

| Topic | Span | Reopened | What kept it open |
|---|---|---|---|
| Poliovirus classification | 05-08 → 08-17 | 6+ in the prior repo, 4 here | It encodes human scientific judgement. Agents kept presenting declines and coarsened labels as the honest outcome. They also tried to rebuild paper-based calls with algorithms, and applied block-level conclusions to records whose own evidence didn't support them. The main rule was rewritten six times in three weeks (e5da1f6). |
| Alignment quality | 06-26 → 08-18, plus 11-09 | about 10 | A codon-aware rebuild regressed a record, and Mike caught it. The fragment gap-opening penalty had never been set in any build (found 07-30). A 50 GB memory wall. Six indel repairs. This is the most-reopened topic. |
| Checks that can actually fail | 07-28 → 08-16 | 11 schema versions in 4 days in the prior repo; 6 here | The recurring defect was a check that could not fail: a contract certifying itself, a test asserting current behaviour instead of the rule, a gate that silently stopped running. |
| `engineered_or_construct` | 07-29 → 08-16 | 4 | About ten commits on 07-29 alone. Headline counts corrected three times. DQ205099 reversed twice. |
| Membership | 06-24 → 07-29 | 4 | Locked, then reopened for these reasons: a batch of exclusions, a record that needed a new positive allowlist, and 245 parechovirus records. |
| Recombinant / chimera labels | 06-26 → 07-31 | 4 | The first tier override was later removed because its premise was wrong. A chimera rule in this repo was built and reverted (5a29095). |
| Keeping the explorer current | 07-30 → 08-18 | 4 | Scheduled watchers failed. Settled by having CI build the site's data from `final/`. |

What closed classification:
- overrides that carry their provenance;
- reproducing the prior repo's mechanisms exactly;
- a final review where evidence decided each case. Some cases overturned Mike's own first read.

What closed the checks:
- independent reviewers;
- the rule that every check has a recorded mutation that makes it fail.

**Easy (one pass, no return):**
- Attribution and institution normalization (05-29).
- Schema v1 lock (06-26).
- The 462 unresolved records: five rounds in one day (07-21), never reopened.
- Whole-genome unified alignments, built overnight (07-25).
- The carve-out itself (07-29).
- Explorer design (07-29) and the alignment raster (08-18).
- Regenerating the source layer byte-for-byte from `raw/` (07-29), and `rules.json` (07-30).
- The 5.0.0 review items, approved one by one (08-12).
- Retiring the weekly alignment build (11-09).

**Patterns:**
- **Friction tracks judgement.** Design, visualization and mechanical work went through in one pass. Anything encoding a scientific judgement took weeks.
- **The repeated agent failure was presenting less as more honest:** declines, coarsening, a narrower result framed as safer. Evidence changed Mike's mind; framing didn't.
- **Mike checked "done" claims himself** ("is the entire plan done?"). Each standing rule in section 3 came from a specific catch.
- **The approval style changed after 08-10.** Report first, then plan, then itemized approval. Most work after that was easy or needed one correction.

## 5. What was reasoned through, and who brought what

Section 4 covers how long decisions took. This one covers how they were decided.

One division held for seven months: **Mike supplied definitions and domain priors, agents supplied
measurement at a scale he could not reach by hand.** Neither half was sufficient alone. His
definitions stayed under-determined until an agent found the records that forced the ambiguity, and
agent measurements stayed inert until he said which clause governed.

### Who owned which kind of decision

| Kind of decision | Example | Who decided |
|---|---|---|
| **Definitions** — what a label asserts | what `engineered` means; what `vouched` means; that `Sabin` records a provenance and `Sabin-like` is what you call the same sequence when it came out of a person or a sewer | Mike alone. No measurement produces these, and most import field convention rather than invent it. |
| **Evidence precedence** — which source wins | a record's own stated host outranks a partition default; a depositor's attestation outranks a computed tier; evidence of how a sample was captured outranks keywords in a paper's title | Mike set the ordering; agents found where it was being violated. |
| **Thresholds** | the published divergence bands | Rarely chosen here — the values are field convention. Agents contributed where a threshold has no right to be applied. |
| **Membership and scope** | which records are in the carve at all | Mike, decisively, twice. |
| **Record identity** | which records are the same material | Agents, by measurement. |
| **Declining or guessing** | 25,051 declined cells instead of a rule that scores 97% | Shared. Agents declined for inputs they did not have; Mike declined for inferences the evidence did not license. |
| **Curation or science** | whether a finding belongs in the data at all | Mike, explicitly and repeatedly. |

### Six decisions worth following

**1. Membership follows the name, not the sequence.** Agents built and calibrated a protein-distance
band to decide whether a record is poliovirus. Mike overturned it on 06-24 with a prior and a
counterexample: poliovirus has been notifiable for decades, so a GenBank organism call is very
likely correct, and the band would have excluded a cluster of real, valuably divergent records.
Membership follows the call; sequence adjudicates only the ambiguous names. The measurement was
right as a measurement and wrong as a rule.

**2. What `engineered` means.** The inherited column was set by a text match on `\bPAT\b` run over a
concatenated blob that included the record's division code, so all 506 patent-division records
shipped TRUE regardless of content. Agents found that. Mike then wrote the definition: someone
assembled that specific genotype for a purpose, and it is not a genotype that occurred in nature;
re-deposits of a natural reference take that reference's label. Agents applied it record by record
and reported back the cases it did not cover. Mike revised his own criterion rather than defend the
records — "revise my criterian to be coherent with what we're actually doing" — and later ruled one
record TRUE on the *construct* half of the column's meaning. That ruling exposed the limit of the
whole review: every instrument in it answers "is this sequence engineered?", and none answers "is
this material a construct?"

**3. A threshold applied where it has no power.** Mike reported five records with the wrong label and
proposed a cause: a parser missing a lowercase country code. Agents checked and falsified it — the
parser already uppercased its input, and no such rule existed. The real cause was the wild/VDPV
boundary applied to a 90-nucleotide window, where one standard error is 2–3 nucleotides. The proof
was internal: records from the same panel split across the boundary. The fix was a panel-level label,
not a threshold change, and the log refuses to generalise it.

**4. The explorer as a falsification instrument.** Mike asked for plots and stated in advance what a
violation would look like: records of one class sitting in another's neighbourhood "must be old
reference strains. otherwise they are probably misclassified." Agents executed and found 154 rows to
flip, plus the exculpating argument for the one survivor — a 1945 isolate that predates any vaccine.
The same screen later found 20 records whose label had come from a paper's title rather than a
measurement. Two of those 20 were Mike's own earlier confirmations, overturned by an alignment that
saw a short in-frame deletion the ungapped comparison had read as 26% divergence.

**5. An inference he refused to encode.** Reading one cluster, Mike concluded the epidemiological
story was obvious, and then declined to put it in the data: "that's an inference, not data, so the
database is correct as is." The same line was drawn repeatedly — a label that no single deposit's
text can carry is not written, however strong the read.

**6. A rule that fitted the answer.** Agents built a rule to recognise the four records a prior
release called chimeric. It reproduced that release's own breakpoint, then fired on 196 records
across the corpus, 192 of them ordinary labels. It was reverted and closed with four record-level
decisions instead. That became the standing test: a threshold tuned until a specific record resolves
is not a rule. Two records sit in an undecided band to this day rather than have a published
threshold moved to catch them.

### What each side brought

**Mike supplied what no measurement produces:**
- **Definitions, and the field conventions behind them.** Most labels are GPLN or WHO usage, not inventions.
- **Fixed points in the world.** That a vaccine reference strain has been frozen for seventy years, so proximity to it settles origin even where the sequence cannot type. That a given year postdates a wild type's elimination, which turns a borderline distance into a settled call.
- **The counterexample classes that break clean rules.** Pre-vaccine-era wild virus that is not far diverged. Seed stocks that drifted before they were frozen. Reference panels in which wild strains appear inside VDPV papers.
- **Instruments, specified down to the metric and its known bias.** He asked for "pairwise deletion fractional distance… I accept this will be a bit off for indels."
- **Knowing when not to spend rigor.** Some edge uncertainty was documented rather than resolved.

**Agents supplied what he could not do by hand:**
- **Whole-corpus measurement**: distances, counts by bucket, byte-identity groups, base composition, coverage tables.
- **Calibration of his qualitative rules.** "Egregiously far away" became a measured boundary with a recovery rate attached.
- **Reading papers at block scale**, including one case where a paper's own figure overturned a label inherited from the prior release.
- **Falsifying the record's own claims.** One patent's description of its deposit was disproved by measuring the deposit.
- **Finding causes no domain knowledge would surface**: a substring collision between two virus names that let 245 out-of-genus records into the carve; a typing step that matched a record against itself and reported the result as confirmation; an alignment parameter that had been at its default in every build ever run.
- **Reporting what they had not checked**, so a later reader can tell "checked, nothing there" from "never examined".

### Where agent reasoning misled

The failures have a shape. They were rarely arithmetic.

- **A good measurement proposed as the wrong kind of object.** The membership band is the clearest case: well calibrated, and wrong as a rule.
- **A well-measured fit to the wrong model.** `sequence_scope` was fitted against coverage geometry to 86.7% with structured errors. The determinant was the record's own annotation; read that way, a rule reproduces the column on all 24,296 shared rows.
- **Bulk rules from a base rate.** A proposal to overwrite 243 disagreements in one direction, on the grounds that the reverse case is rare, ignored why those records exist.
- **Less presented as more honest.** Declines and coarsened labels were framed as the conservative choice until Mike rejected the framing: a coarsened value is a lost judgement, not a safe one.
- **A check that cannot fail.** A contract that certified itself; an invariant entailed by its neighbours; a guard placed in the display layer while the upstream decision went untouched; a regression test pinning a known-wrong value.
- **A consequence of a design choice read as evidence for it.** One agent concluded a narrower alignment was worse, then retracted it the same day after its own measurement.

Mike caught these by asking what a number *means* rather than whether it validates — including about a column he had just approved for deletion.

### Where evidence changed Mike's position, and where it did not

**It changed:**
- He withdrew a near-threshold exception he expected to hold, once shown the records sat on the wrong side of a published boundary, preferring the rule applied uniformly.
- He dropped an instruction to promote a record to reference status after an agent asked what that would actually set.
- Four of his own `engineered` confirmations were retired on sequence evidence, and two `wild` confirmations were overturned by an alignment.
- He reversed his own design preference on how uncertain dates ship, then went further than the agent proposed.
- His cause for a batch of wrong labels was falsified, and he accepted the measured cause.

**It did not change:**
- The paper-based calls. Agents measured that 97% of the gap was declines or coarsening and presented that as acceptable; he rejected the framing outright and required the calls to survive the rewrite.
- The curation/science line.
- The refusal to move a published threshold to catch a record.

The asymmetry is worth naming: he overruled agent *recommendations* a handful of times, and he almost never disputed an agent *measurement*. When a measurement contradicted him he took it, and when a recommendation overreached he rewrote the criterion rather than bend the data.

## 6. Deciding the final product

**06-24.** The dataset is ruled out of scope for the prior repo's public material, and will become its own repo.

**07-24: the design contract.**
- The goal is "a standalone public good".
- It has two co-equal deliverables: the data, and a pipeline that rebuilds the data from raw inputs "without being inside my head".

**What ships:**
- all pure data;
- one canonical cleaned variable per field with complex decision logic;
- clean MSAs: "final fasta should be an MSA. save downstream user the work";
- exclusion reasons;
- a dictionary for every file and column.

**What doesn't ship:**
- intermediates;
- old hand-derived alignments;
- copyrighted papers and patents, which are cited instead;
- internal provenance notes.

Code is MIT, data is CC0, with a citation request.

**07-29.** 2.1.5 published byte-for-byte as a frozen data release, with the reproducibility claim stated as open. Over the next day the prior repo kept fixing data, and this repo re-imported 2.3.0 and 2.4.1.

**07-31: a three-step path.**
1. The alignment layer goes into `main`.
2. A metadata clean.
3. Releases are built only from `main`.

3.0.0 that day was the first release built from `raw/` and `registry/` alone.

**08-12.** The repo should eventually carry no dependency on, or reference to, the prior private repo. 5.0.0 (08-16) did that.
- 2.4.1 is kept only as a comparison fixture under `releases/`.
- Every difference from it is declared.
- References to the prior repo were removed.

**The explorer.** Its job was set on day one: a surface that reveals structure and makes misclassification visible. It became the instrument of the vouched review.

**Still open:**
- `final/audit/sequence_evidence.tsv.gz` has no producer in this repo.
- The non-polio records have not had the vouched review.
- `M29182` and `M29183` ship blank `sample_origin` and `surveillance_stream` where 2.4.1 shipped
  `non-human` and `engineered/lab`. They hold no `origin_class` or `sampling_frame` row, and no
  curator has ruled on them. It is the same gap 5.3.0 closed for `M30213` and `M30219`.
- `docs/rule-redundant-curation.md` is a dated analysis whose headline count has since moved from
  531 to 529; the live tally in `docs/reproducibility.md` is the one kept current.

## How this history was put together

**Sources:**
- this repo: 207 commits (07-29 → 11-09), `docs/`, `registry/`;
- the prior private repo: its decision log, working notes and 242 commits (04-30 → 07-30). That repo is not public, so claims sourced there cannot be checked from here;
- Mike's messages to agents in both repos from 05-28 onward, about 900 once duplicates are removed. Sessions before 05-28 were not available.

**Method:**
- Agents read the sources and drafted the summary.
- Figures and quotes were checked against the commits and the original text before inclusion.
- Sign-off was judged from shifts in focus, as section 4 describes.
