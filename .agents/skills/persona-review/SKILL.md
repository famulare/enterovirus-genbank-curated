---
name: persona-review
description: Use when reviewing a draft, manuscript, proposal, memo, or argument from one or more specified audience or expert personas. Supports adversarial review, supportive review, and steelman-plus-red-team review. Uses persona examples only to calibrate professional standards and likely concerns; do not impersonate living people.
---

# Persona Review

Review a document through specified audience, disciplinary, institutional, or expert lenses.
This is critique and positioning work, not prose editing. Do not rewrite the document unless
explicitly asked after the review.

## Core rule

Adopt the persona's **standards of evidence, likely priors, vocabulary of concern, and
professional incentives**. Do **not** mimic a named living person's voice, style, or identity.
If the user names real people, treat them as calibration examples for a reviewer type.

## Modes

Name the mode before acting.

### ADVERSARIAL REVIEW

Use when the user wants a skeptical, reviewer-2, red-team, or pressure-test pass.
Ask: what would this reviewer reject, distrust, or require before accepting the stronger
claims?

Default output:

1. Major concerns
2. Minor / technical concerns
3. What would strengthen the work
4. Claims or framings most at risk of being misread

### SUPPORTIVE REVIEW

Use when the user wants to know what is especially strong, novel, useful, or well positioned
relative to adjacent literature, practice, or institutional needs.
Ask: what would this reviewer value, cite, defend, or encourage the authors to emphasize?

Default output:

1. Strongest contributions
2. What is unusually valuable relative to related work
3. Under-leveraged strengths or framing opportunities
4. Audiences likely to respond well
5. Claims that can be made more confidently, if evidence supports them

### STEELMAN + RED TEAM

Use when the user wants both the best case and the hardest fair critique from the same lens.
This is often the best pre-revision mode.

Default output:

1. Steelman: the strongest version of what the work contributes
2. Red team: what still fails, overreaches, or needs evidence
3. Revision implications: what to preserve, sharpen, soften, or test

## Workflow

1. Identify the document or bounded unit under review.
2. Identify each persona lens and the selected mode.
3. If current or external context would materially improve the persona calibration, use search
   or primary/public sources. Keep this lightweight unless the user asks for deep research.
4. State whether search was used and what it was used for: persona calibration, related
   literature, institutional context, or factual verification.
5. Review the manuscript's claims against the persona's standards. Separate:
   - what the document itself shows;
   - what outside context suggests;
   - what is inference by the reviewer.
6. End with actionable revision implications, not only judgment.

## Multiple personas

When reviewing from multiple lenses:

- Keep the reviews separate first; do not prematurely synthesize away disagreement.
- If subagents are available and the user requests independent reviews, spawn one per lens.
- After separate reviews, optionally add a short cross-review synthesis:
  - shared objections;
  - lens-specific objections;
  - likely highest-priority revisions;
  - tensions between audiences.

## Search guidance

Use search when the persona depends on current literature, current policy, institutional
practice, named examples, or field-specific gray literature. Prefer primary sources,
official institutional documents, and representative publications. Search is for calibration
and factual grounding, not for manufacturing claims the document does not support.

When named people are provided as examples:

- Search may be used to infer their professional domain, publication topics, institutional
  role, and evidentiary standards.
- Do not write "as" that person.
- Do not claim the person would hold a view unless directly sourced and relevant.
- Phrase the lens as, for example, "a skeptical polio laboratory reviewer" or "a GPEI field
  operations reviewer," not as the named individual.

## Output discipline

- Be candid and concrete; do not be performatively harsh.
- Ground critique in the document's claims, structure, methods, and evidence chain.
- Do not invent missing evidence. Mark it as needed.
- Preserve uncertainty: distinguish "unsupported," "under-specified," "plausible but not
  shown," and "likely wrong."
- For high-stakes scientific, medical, legal, financial, or policy implications, explicitly
  identify what would be harmed or misled if the current framing were wrong.
- If asked to write the review to a file, create a clearly named artifact and do not edit the
  source document unless explicitly requested.
