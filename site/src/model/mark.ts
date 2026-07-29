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

export interface MarkSet {
  marks: Mark[];
  /** Everything the chapter wants to say about this panel, already counted. */
  facts: PanelFacts;
}

export interface PanelFacts {
  region: string;
  total: number;
  minNt: number;
  columns: number;
  excludedBelowCoverage: number;
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
): { x: Axis; y: Axis } {
  const span = (get: (m: Mark) => number): [number, number] => {
    let low = Infinity;
    let high = -Infinity;
    for (const mark of marks) {
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
