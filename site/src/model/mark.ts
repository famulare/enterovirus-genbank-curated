/** What a scatter draws, independent of which figure produced it.
 *
 *  Both figure sets place one mark per sequence and colour it by the same trait, so
 *  they share a renderer, a legend, an inspect/pin interaction and a brush. They
 *  differ only in where the marks come from and what the readout says about one. This
 *  is the shape that boundary takes.
 */

import type { AxisScale } from "./view.js";
import type { Axis } from "./panel.js";

export interface Mark {
  /** Index into records.json. */
  record: number;
  /** Drawn position, in data units, with any jitter already applied. */
  x: number;
  y: number;
  /** Multiplier on the mark radius. Below 1 means "this position is less certain".
   *
   *  Size rather than fill, because fill is already spoken for: the categorical
   *  glyphs use filled-versus-open to separate palette slot n from slot n+4, so
   *  overloading it would make a thin slot-5 point indistinguishable from a confident
   *  slot-1 one. Size is a free channel and reads the right way round. */
  weight: number;
  /** Drawn with a cross through it — a record whose value should not be trusted at
   *  face value, whatever its position. */
  flagged: boolean;
}

/** A straight segment in data coordinates, drawn beneath the marks.
 *
 *  Only a tree needs these — its marks are joined by branches, where a scatter's are
 *  independent — but they belong here rather than in the tree model, because what the
 *  renderer draws should not depend on which figure asked for it. */
export interface Link {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export interface MarkSet {
  marks: Mark[];
  /** Everything the chapter wants to say about this panel, already counted. */
  facts: PanelFacts;
  /** Structure joining the marks, for a figure that has any. */
  links?: Link[];
}

export interface PanelFacts {
  region: string;
  total: number;
  /** Coverage floor a record had to clear to appear, in `unit`. */
  minNt: number;
  /** Region width, in `unit`. */
  columns: number;
  /** What this figure counts and compares — nucleotides, or codons for a figure that
   *  translates first. A figure that reported a codon threshold as a nucleotide one
   *  would understate its own floor by a factor of three. */
  unit: string;
  excludedBelowCoverage: number;
  /** How many records cleared the coverage floor, when that is more than the figure
   *  draws. A tree needs a complete distance matrix and so cannot carry everything
   *  eligible; the two scatters can, and leave this unset. */
  eligible?: number;
  /** Region-specific extras the note renders verbatim, in order. */
  notes: string[];
}

/** Axis pair for a set of marks. Anchored at zero when every value is non-negative —
 *  zero is then a real, occupied position — and centred on the data otherwise, which
 *  is what a signed embedding coordinate needs. */
export function markExtent(
  marks: Mark[],
  scale: AxisScale,
  axis: (min: number, max: number, scale: AxisScale) => Axis,
  /** Set the range from the confidently-placed marks only.
   *
   *  For a figure whose positions vary in trustworthiness, letting the least reliable
   *  mark define the frame contradicts the encoding: a thin mark is already drawn
   *  smaller *because* its position is approximate. On PV1's protein scaling, seven
   *  records with 19 readable codons out of 881 stretched the second axis to 1.66 and
   *  squashed 3,158 confident placements into 3% of it. Thin marks inside the resulting
   *  range still draw; the figure states how many fall outside. Only a scatter may do
   *  this — clipping a tree's tip would leave its branch running off the panel. */
  confidentOnly = false,
): { x: Axis; y: Axis } {
  const framing = confidentOnly ? marks.filter((mark) => mark.weight >= 1) : marks;
  // Fall back to everything rather than to an empty range: a panel where nothing is
  // confidently placed still has to draw.
  const basis = framing.length ? framing : marks;
  const span = (get: (m: Mark) => number): [number, number] => {
    let low = Infinity;
    let high = -Infinity;
    for (const mark of basis) {
      const value = get(mark);
      if (value < low) low = value;
      if (value > high) high = value;
    }
    if (!Number.isFinite(low)) return [0, 1];
    if (low >= 0) return [0, high * 1.04];
    // Symmetric padding, so a signed axis does not appear to lean.
    const pad = (high - low) * 0.04 || Math.abs(high) * 0.04 || 1;
    return [low - pad, high + pad];
  };

  const [x0, x1] = span((m) => m.x);
  const [y0, y1] = span((m) => m.y);
  return { x: axis(x0, x1, scale), y: axis(y0, y1, scale) };
}
