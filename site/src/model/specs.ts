/** The four chapter specifications: what each figure set contributes beyond the shared
 *  instrument in ui/chapter.ts.
 *
 *  All four place one mark per sequence, color it by the same trait and answer the same
 *  kind of question about the same records, so they share one renderer, one legend, one
 *  hover, one keyboard traversal and one brush. What a spec supplies is where its marks
 *  come from and what a readout says about one. The two trees additionally supply a link
 *  layer; in every other respect they are the same instrument as the two scatters.
 */

import { assertPanelSchema, type DistanceRegion, type PanelFile } from "./panel.js";
import { assertTreeSchema, links as treeLinks, type TreeFile, type TreeRegion } from "./tree.js";
import { loadFile } from "./source.js";
import type { ChapterSpec } from "../ui/chapter.js";
import type { Mark, MarkSet } from "./mark.js";
import type { Records } from "./records.js";

function rate(numerator: number, denominator: number): string {
  return denominator === 0 ? "—" : (numerator / denominator).toFixed(4);
}

function n(value: number): string {
  return value.toLocaleString("en-US");
}

/** Decode every region of one source file into a mark set apiece. The file is fetched
 *  through the shared cache, so the two chapters reading it fetch it once. */
async function decodeAll<F>(
  path: string,
  assert: (file: F) => F,
  regions: string[],
  decode: (file: F, region: string) => MarkSet,
): Promise<Map<string, MarkSet>> {
  const file = assert(await loadFile<F>(path));
  return new Map(regions.map((region) => [region, decode(file, region)]));
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
    coverage: number;
  }
>();

/** The panel-scoped numeric a color scale can paint by. Without this,
 *  `region_coverage_nt` sat in the color menu returning null for every record and
 *  painted the whole panel one gray. */
export function coverageOf(mark: Mark): number | null {
  return (
    divergenceDetail.get(mark)?.coverage ??
    distanceDetail.get(mark)?.coverage ??
    treeDetail.get(mark)?.coverage ??
    null
  );
}

function divergenceMarks(file: PanelFile, region: string): MarkSet {
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
      coverage: raw.coverage[i]!,
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
      unit: "nt",
      excludedBelowCoverage: raw.excluded.below_coverage,
      notes,
    },
  };
}

export const DIVERGENCE: ChapterSpec = {
  id: "divergence",
  regionFlag: "in_divergence",
  title: "Divergence",
  xLabel: "Synonymous differences per codon compared",
  yLabel: "Non-synonymous per codon compared",
  honorsScale: true,

  sets(selection, regions) {
    return decodeAll<PanelFile>(
      `data/panels/${selection}.json`,
      assertPanelSchema,
      regions,
      divergenceMarks,
    );
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
      ["Region coverage", `${n(d.coverage)} nt`],
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

const distanceDetail = new WeakMap<
  Mark,
  { resolved: number; landmarks: number; transform: string; coverage: number; unit: string }
>();

/** One decoder for both scaling figures. Nucleotide and residue space run the same
 *  procedure over the same metric, so the only thing that differs is which block of the
 *  panel file it reads and what a difference means once read. */
function distanceMarks(
  raw: DistanceRegion | undefined,
  region: string,
  scale: string,
  what: "nucleotide" | "residue",
): MarkSet {
  if (!raw) throw new Error(`no ${what} distance region ${region}`);
  const fit = raw.transforms[scale] ?? raw.transforms.linear!;
  const thin = new Set(raw.thin);
  const marks: Mark[] = raw.record.map((record, i) => {
    const mark: Mark = {
      record,
      x: fit.x[i]!,
      y: fit.y[i]!,
      // Thin placements are drawn smaller rather than unfilled, because fill is
      // already carrying the categorical glyph's identity.
      weight: thin.has(i) ? 0.62 : 1,
      flagged: false,
    };
    distanceDetail.set(mark, {
      resolved: raw.resolved[i]!,
      landmarks: raw.landmarks,
      transform: scale,
      coverage: raw.coverage[i]!,
      unit: raw.unit,
    });
    return mark;
  });

  const notes = [
    `Scaling the ${
      scale === "sqrt" ? "square roots of the" : ""
    } ${what} distances, against ${n(raw.landmarks)} landmark sequences whose distances are
     all defined; two dimensions carry ${(fit.explained * 100).toFixed(0)}% of the variance.`,
  ];
  if (what === "residue") {
    notes.push(
      `A codon counts only where all three of its bases are unambiguous in both sequences,
       so a synonymous change moves nothing here.`,
    );
  }
  if (fit.negative_share > 0.005) {
    notes.push(
      `${(fit.negative_share * 100).toFixed(1)}% of the geometry is non-Euclidean, so
       distances in this plane understate some real separations${
         scale === "sqrt" ? "" : " — the square-root scale usually reduces this"
       }.`,
    );
  } else {
    notes.push("The geometry is Euclidean, so a plane can hold it without distortion.");
  }
  if (thin.size) {
    notes.push(
      `${n(thin.size)} are drawn smaller: they overlap too few landmarks for a confident
       position, and sit nearer the center than they should.`,
    );
  }

  return {
    marks,
    facts: {
      region,
      total: marks.length,
      minNt: raw.min_nt,
      columns: raw.columns,
      unit: raw.unit,
      excludedBelowCoverage: raw.excluded.below_coverage,
      notes,
    },
  };
}

export const DISTANCE: ChapterSpec = {
  id: "distance",
  regionFlag: "in_distance",
  title: "Distance",
  xLabel: "Scaling axis 1 (arbitrary units)",
  yLabel: "Scaling axis 2",
  frameFromConfident: true,
  // The scale control selects which embedding to show — the one fitted to the
  // distances, or the one fitted to their square roots — rather than transforming the
  // drawn axis. The coordinates are signed, so the axis itself is always linear;
  // `honorsScale` governs the axis, and is false for exactly that reason.
  honorsScale: false,

  sets(selection, regions, scale) {
    return decodeAll<PanelFile>(
      `data/panels/${selection}.json`,
      assertPanelSchema,
      regions,
      (file, region) => distanceMarks(file.distance[region], region, scale, "nucleotide"),
    );
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
      ["Region coverage", `${n(d.coverage)} ${d.unit}`],
      ["Scaling axis 1", mark.x.toFixed(4)],
      ["Scaling axis 2", mark.y.toFixed(4)],
      ["Dissimilarity scaled", d.transform === "sqrt" ? "square root of distance" : "distance"],
      ["Landmark distances defined", `${n(d.resolved)} of ${n(d.landmarks)}`],
      ["Placement", mark.weight < 1 ? "thin — treat position as approximate" : "confident"],
      [
        "Region width",
        `${n(set.facts.columns)} ${set.facts.unit === "nt" ? "alignment columns" : set.facts.unit}`,
      ],
    ];
  },
};

/** Figure set 4: the same scaling in protein space.
 *
 *  Worth its own chapter rather than a toggle on set 2, because the comparison a reader
 *  makes is between the two pictures: structure that survives translation is structure in
 *  the protein, and structure that vanishes was synonymous all along. */
export const PROTEIN_DISTANCE: ChapterSpec = {
  id: "distance-aa",
  regionFlag: "in_protein_distance",
  title: "Protein distance",
  xLabel: "Scaling axis 1 (arbitrary units)",
  yLabel: "Scaling axis 2",
  honorsScale: false,
  frameFromConfident: true,

  sets(selection, regions, scale) {
    return decodeAll<PanelFile>(
      `data/panels/${selection}.json`,
      assertPanelSchema,
      regions,
      (file, region) =>
        distanceMarks(file.protein_distance[region], region, scale, "residue"),
    );
  },

  readout: DISTANCE.readout,
  measured: DISTANCE.measured,
};

// --- Figure sets 3 and 4: the two phylogenies -------------------------------

const treeDetail = new WeakMap<
  Mark,
  {
    coverage: number;
    shared: number;
    unit: string;
    tips: number;
    depth: number;
    root: string;
    confidentShared: number;
  }
>();

/** Tips as marks, branches as links.
 *
 *  A tip's y is its position in the ladder, which is an ordering and not a quantity —
 *  hence the ordinal axis. Its x is distance from the root in the same uncorrected
 *  currency as the rest of the site.
 */
function treeMarks(
  tree: TreeRegion,
  region: string,
  whole: string,
  scale: string,
): MarkSet {
  const thin = new Set(tree.thin);
  const depth = tree.tip_x.reduce((most, value) => Math.max(most, value), 0);
  const marks: Mark[] = tree.tip_record.map((record, index) => {
    const mark: Mark = {
      record,
      x: tree.tip_x[index]!,
      y: index,
      weight: thin.has(index) ? 0.62 : 1,
      flagged: false,
    };
    treeDetail.set(mark, {
      coverage: tree.tip_coverage[index]!,
      shared: tree.tip_shared[index]!,
      unit: tree.unit,
      tips: tree.tip_record.length,
      depth,
      root: tree.root.label,
      confidentShared: tree.confident_shared,
    });
    return mark;
  });

  const notes: string[] = [];
  const dropped = tree.excluded.not_comparable;
  if (scale === "sqrt") {
    notes.push(
      `Drawn on a square-root axis, because a handful of deeply divergent sequences would
       otherwise compress the rest of the tree into the leftmost tenth of the panel. Every
       node still reads its distance from the root off the axis; what a square root gives up
       is that a branch's drawn length is no longer the sum of the branches inside it. Switch
       to the linear scale for additive branch lengths.`,
    );
  }
  notes.push(
    tree.root.kind === "outgroup"
      ? `Rooted on ${tree.root.label}, at the midpoint of its own branch.`
      : "Rooted at the midpoint of the longest tip-to-tip path — non-polio enterovirus has no member ancestral to the rest, so nominating an outgroup would assert something untrue.",
  );
  if (dropped) {
    notes.push(
      `Neighbor joining needs a distance for every pair, and ${n(dropped)} sequences overlap
       the rest too little for one to exist, so they are left off. Those sequences are in the
       two views above, which need no complete matrix.`,
    );
  }
  if (tree.negative_branches) {
    notes.push(
      `${n(tree.negative_branches)} branches came out negative and were set to zero,
       ${tree.clamped_total.toFixed(4)} in total: real distances are never exactly
       additive, and neighbor joining absorbs the discrepancy into branch lengths.`,
    );
  }
  if (thin.size) {
    notes.push(
      `${n(thin.size)} tips are drawn smaller: their distances rest on fewer than
       ${n(tree.confident_shared)} shared ${whole}, so treat the length of those
       branches as approximate.`,
    );
  }

  return {
    marks,
    links: treeLinks(tree),
    facts: {
      region,
      total: marks.length,
      minNt: tree.min_shared,
      columns: tree.columns,
      unit: tree.unit,
      eligible: tree.n_eligible,
      excludedBelowCoverage: tree.excluded.below_coverage,
      notes,
    },
  };
}

/** Tips are drawn small on purpose. A 2,500-tip ladder gives each tip a third of a
 *  pixel of height, so a dot sized for a scatter would merge into a solid bar and hide
 *  the very thing the figure is for — one differently-colored tip inside a clade. */
function tipRadius(count: number, thumbnail = false): number {
  if (thumbnail) return count > 1200 ? 0.7 : 1;
  if (count > 1800) return 1.5;
  if (count > 700) return 1.9;
  return 2.6;
}

function treeReadout(mark: Mark): string[] {
  const d = treeDetail.get(mark);
  if (!d) return [];
  return [
    `${mark.x.toFixed(4)} from the root${
      d.depth > 0 ? ` · ${((mark.x / d.depth) * 100).toFixed(0)}% of the deepest tip` : ""
    }`,
    `typically ${n(d.shared)} ${d.unit} shared with the other tips${
      mark.weight < 1 ? " · thin, so this branch length is approximate" : ""
    }`,
  ];
}

function treeMeasured(set: MarkSet, mark: Mark, unitLabel: string): [string, string][] {
  const d = treeDetail.get(mark);
  if (!d) return [];
  return [
    ["Region coverage", `${n(d.coverage)} ${d.unit}`],
    ["Distance from root", mark.x.toFixed(5)],
    ["Position in the ladder", `${n(mark.y + 1)} of ${n(d.tips)}`],
    ["Typically shared with other tips", `${n(d.shared)} ${d.unit}`],
    [
      "Branch length",
      mark.weight < 1
        ? `approximate — under ${n(d.confidentShared)} shared ${d.unit}`
        : "rests on substantial overlap",
    ],
    ["Rooted on", d.root],
    ["Region width", `${n(set.facts.columns)} ${unitLabel}`],
  ];
}

export const NUCLEOTIDE_TREE: ChapterSpec = {
  id: "phylogeny-nt",
  regionFlag: "in_nucleotide_tree",
  title: "Nucleotide tree",
  xLabel: "Distance from the root (differences per nucleotide compared)",
  // No label: the vertical position is a place in an ordering, and naming it as though
  // it were a measured quantity would invite a reading that is not there.
  yLabel: "",
  yAxis: "ordinal",
  // The scale control reaches the axis here, as it does in figure 1. A few sequences sit
  // six times deeper than the 99th percentile — and they are not the thin ones, they are
  // sequences with solid overlap and genuinely large distances, which is to say they are
  // the misclassification this page exists to surface. Hiding them is not an option, and
  // on a linear axis they flatten everything else. The square root spreads the crowded
  // near-root region; the note says what that costs.
  honorsScale: true,
  tall: true,
  radius: tipRadius,

  sets(selection, regions, scale) {
    return decodeAll<TreeFile>(
      `data/trees/${selection}.json`,
      assertTreeSchema,
      regions,
      (file, region) => {
        const tree = file.nucleotide[region];
        if (!tree) throw new Error(`${file.selection} has no nucleotide tree for ${region}`);
        return treeMarks(tree, region, "nucleotides", scale);
      },
    );
  },

  readout(_records, _set, mark) {
    return treeReadout(mark);
  },

  measured(set, mark) {
    return treeMeasured(set, mark, "alignment columns");
  },
};

export const PROTEIN_TREE: ChapterSpec = {
  id: "phylogeny-aa",
  regionFlag: "in_protein_tree",
  title: "Protein tree",
  xLabel: "Distance from the root (differences per residue compared)",
  yLabel: "",
  yAxis: "ordinal",
  honorsScale: true,
  tall: true,
  radius: tipRadius,

  sets(selection, regions, scale) {
    return decodeAll<TreeFile>(
      `data/trees/${selection}.json`,
      assertTreeSchema,
      regions,
      (file, region) => {
        const tree = file.protein[region];
        if (!tree) throw new Error(`${file.selection} has no protein tree for ${region}`);
        return treeMarks(tree, region, "codons", scale);
      },
    );
  },

  readout(_records, _set, mark) {
    return treeReadout(mark);
  },

  measured(set, mark) {
    return treeMeasured(set, mark, "codons");
  },
};
