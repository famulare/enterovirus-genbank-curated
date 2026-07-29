/** The two chapter specifications: what each figure set contributes beyond the shared
 *  instrument in ui/chapter.ts. */

import type { ChapterSpec } from "../ui/chapter.js";
import type { Mark, MarkSet } from "./mark.js";
import type { PanelFile } from "./panel.js";
import type { Records } from "./records.js";

function rate(numerator: number, denominator: number): string {
  return denominator === 0 ? "—" : (numerator / denominator).toFixed(4);
}

function n(value: number): string {
  return value.toLocaleString("en-US");
}

// --- Figure set 1: divergence from reference --------------------------------

/** Per-mark divergence numbers, kept beside the marks so the readout can quote exact
 *  counts rather than a rounded rate. */
const divergenceDetail = new WeakMap<
  Mark,
  {
    synonymous: number;
    nonsynonymous: number;
    comparable: number;
    assessable: number;
    indelCodons: number;
    indelEvents: number;
    reference: string;
    referenceKind: string;
  }
>();

export const DIVERGENCE: ChapterSpec = {
  id: "divergence",
  regionFlag: "in_divergence",
  xLabel: "Synonymous differences per codon compared",
  yLabel: "Non-synonymous per codon compared",
  honoursScale: true,

  marks(file: PanelFile, region: string): MarkSet {
    const raw = file.divergence[region];
    if (!raw) throw new Error(`${file.selection} has no divergence region ${region}`);
    const shifted = new Set(raw.frameshift);
    const marks: Mark[] = raw.record.map((record, i) => {
      const assessable = raw.assessable[i]!;
      const x = raw.synonymous[i]! / assessable;
      const y = raw.nonsynonymous[i]! / assessable;
      // Jitter amplitude is a fraction of one count, so it shrinks as the denominator
      // grows: a whole genome needs less nudging than a 17-codon fragment.
      const step = file.jitter_amplitude / assessable;
      const mark: Mark = {
        record,
        x: x + (raw.jitter_x[i]! / file.jitter_scale) * step,
        y: y + (raw.jitter_y[i]! / file.jitter_scale) * step,
        weight: 1,
        flagged: shifted.has(i),
      };
      const reference = raw.references[raw.reference[i]!];
      divergenceDetail.set(mark, {
        synonymous: raw.synonymous[i]!,
        nonsynonymous: raw.nonsynonymous[i]!,
        comparable: raw.comparable[i]!,
        assessable,
        indelCodons: raw.indel_codons[i]!,
        indelEvents: raw.indel_events[i]!,
        reference: reference?.label ?? "reference",
        referenceKind: reference?.kind ?? "—",
      });
      return mark;
    });

    const kinds = new Set(raw.references.map((r) => r.kind));
    const notes: string[] = [];
    if (raw.excluded.no_reference) {
      notes.push(
        `${n(raw.excluded.no_reference)} have no comparable reference — their virus type is
         unrecorded or holds too few sequences to support a consensus — so they are reported
         unmeasurable here rather than compared to a broader consensus that would not mean the
         same thing. They still appear in the distance view.`,
      );
    }
    notes.push(
      raw.references.length === 1
        ? `Measured against ${raw.references[0]?.label ?? "reference"}.`
        : `Measured against ${n(raw.references.length)} references — ${
            kinds.has("sabin") ? "Sabin for poliovirus, " : ""
          }a consensus of the record's own virus type otherwise.`,
    );
    // The count and its meaning are in the legend, beside the glyph itself; repeating
    // the explanation here would be a second place for a reader to reconcile.
    const flagged = shifted.size;
    if (flagged) {
      notes.push(
        flagged === 1
          ? "One sequence is crossed — see the legend."
          : `${n(flagged)} sequences are crossed — see the legend.`,
      );
    }

    return {
      marks,
      facts: {
        region,
        total: marks.length,
        minNt: raw.min_nt,
        columns: raw.codons * 3,
        excludedBelowCoverage: raw.excluded.below_coverage,
        notes,
      },
    };
  },

  readout(_records: Records, _set: MarkSet, mark: Mark): string[] {
    const d = divergenceDetail.get(mark);
    if (!d) return [];
    return [
      `<b>${d.synonymous}</b> syn, <b>${d.nonsynonymous}</b> non-syn over
       <b>${n(d.assessable)}</b> codons → ${rate(d.synonymous, d.assessable)},
       ${rate(d.nonsynonymous, d.assessable)}`,
      `vs ${d.reference}${d.indelCodons ? ` · ${d.indelCodons} indel codon(s)` : ""}${
        mark.flagged ? " · frameshifting indel" : ""
      }`,
    ];
  },

  measured(_set: MarkSet, mark: Mark): [string, string][] {
    const d = divergenceDetail.get(mark);
    if (!d) return [];
    return [
      ["Codons compared", n(d.assessable)],
      ["— both unambiguous", n(d.comparable)],
      ["— touched by an indel", n(d.indelCodons)],
      [
        "Synonymous differences",
        `${n(d.synonymous)} (${rate(d.synonymous, d.assessable)} per codon)`,
      ],
      [
        "Non-synonymous differences",
        `${n(d.nonsynonymous)} (${rate(d.nonsynonymous, d.assessable)} per codon)`,
      ],
      ["Indel events", d.indelEvents ? n(d.indelEvents) : "none"],
      ["Reading frame", mark.flagged ? "frameshifting indel present" : "intact"],
      ["Measured against", `${d.reference} (${d.referenceKind})`],
    ];
  },
};

// --- Figure set 2: nucleotide distance --------------------------------------

const distanceDetail = new WeakMap<Mark, { resolved: number; landmarks: number }>();

export const DISTANCE: ChapterSpec = {
  id: "distance",
  regionFlag: "in_distance",
  xLabel: "Scaling axis 1 (arbitrary units)",
  yLabel: "Scaling axis 2",
  // Coordinates are signed and have no meaningful zero end, so a square root has
  // nothing to spread and no real value below zero. Always linear.
  honoursScale: false,

  marks(file: PanelFile, region: string): MarkSet {
    const raw = file.distance[region];
    if (!raw) throw new Error(`${file.selection} has no distance region ${region}`);
    const thin = new Set(raw.thin);
    const marks: Mark[] = raw.record.map((record, i) => {
      const mark: Mark = {
        record,
        x: raw.x[i]!,
        y: raw.y[i]!,
        // Thin placements are drawn smaller rather than unfilled, because fill is
        // already carrying the categorical glyph's identity.
        weight: thin.has(i) ? 0.62 : 1,
        flagged: false,
      };
      distanceDetail.set(mark, { resolved: raw.resolved[i]!, landmarks: raw.landmarks });
      return mark;
    });

    const notes = [
      `Placed against ${n(raw.landmarks)} landmark sequences whose distances are all
       defined; two dimensions carry ${(raw.explained * 100).toFixed(0)}% of the variance.`,
    ];
    if (raw.negative_share > 0.05) {
      notes.push(
        `${(raw.negative_share * 100).toFixed(0)}% of the geometry is non-Euclidean, so
         distances in this plane understate some real separations.`,
      );
    }
    if (thin.size) {
      notes.push(
        `${n(thin.size)} are drawn smaller: they overlap too few landmarks for a confident
         position, and sit nearer the centre than they should.`,
      );
    }

    return {
      marks,
      facts: {
        region,
        total: marks.length,
        minNt: raw.min_nt,
        columns: raw.columns,
        excludedBelowCoverage: raw.excluded.below_coverage,
        notes,
      },
    };
  },

  readout(_records: Records, _set: MarkSet, mark: Mark): string[] {
    const d = distanceDetail.get(mark);
    if (!d) return [];
    return [
      `at (${mark.x.toFixed(3)}, ${mark.y.toFixed(3)})`,
      `${n(d.resolved)} of ${n(d.landmarks)} landmark distances defined${
        mark.weight < 1 ? " · thinly placed" : ""
      }`,
    ];
  },

  measured(set: MarkSet, mark: Mark): [string, string][] {
    const d = distanceDetail.get(mark);
    if (!d) return [];
    return [
      ["Scaling axis 1", mark.x.toFixed(4)],
      ["Scaling axis 2", mark.y.toFixed(4)],
      ["Landmark distances defined", `${n(d.resolved)} of ${n(d.landmarks)}`],
      ["Placement", mark.weight < 1 ? "thin — treat position as approximate" : "confident"],
      ["Region width", `${n(set.facts.columns)} alignment columns`],
    ];
  },
};
