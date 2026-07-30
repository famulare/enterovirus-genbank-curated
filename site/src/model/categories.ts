/** Assigning categories to palette slots, and values to colors.
 *
 *  Two rules that matter more than they look:
 *
 *  **Color follows the entity, not its rank.** Slots are assigned over the whole
 *  selection, never over the filtered subset, so toggling a filter cannot repaint
 *  the categories that survive it.
 *
 *  **A declared order beats frequency.** `poliovirus_classification` has a
 *  controlled vocabulary whose rarest member — `Sabin`, 46 records — is the
 *  reference every polio panel is measured against. Ranking by count would fold it
 *  into `Other`.
 */

import type { Summary, Trait } from "./types.js";
import * as palette from "./palette.js";
import type { Records } from "./records.js";

export const OTHER = "Other";
export const MISSING = "not recorded";

export interface Category {
  value: string;
  label: string;
  slot: number;
  count: number;
  swatch: palette.Swatch;
}

export interface DiscreteScale {
  kind: "discrete";
  trait: Trait;
  categories: Category[];
  /** Raw value -> slot. Absent means Other; empty string means not recorded. */
  slotOf: Map<string, number>;
  otherCount: number;
  missingCount: number;
}

export interface ContinuousScale {
  kind: "continuous";
  trait: Trait;
  min: number;
  max: number;
  missingCount: number;
}

export type Scale = DiscreteScale | ContinuousScale;

export function buildScale(
  summary: Summary,
  records: Records,
  trait: Trait,
  rows: number[],
  valueFor?: (row: number) => string,
  /** For a trait that is not a record column — a per-panel measurement, say. */
  numberFor?: (row: number) => number | null,
): Scale {
  if (trait.kind === "continuous") {
    let min = Infinity;
    let max = -Infinity;
    let missing = 0;
    for (const row of rows) {
      const value = numberFor ? numberFor(row) : records.number(trait.id, row);
      if (value === null) missing += 1;
      else {
        if (value < min) min = value;
        if (value > max) max = value;
      }
    }
    if (min > max) {
      min = 0;
      max = 1;
    }
    return { kind: "continuous", trait, min, max, missingCount: missing };
  }

  const counts = new Map<string, number>();
  for (const row of rows) {
    const value = valueFor ? valueFor(row) : records.text(trait.id, row);
    counts.set(value, (counts.get(value) ?? 0) + 1);
  }

  const missingCount = counts.get("") ?? 0;
  counts.delete("");

  const declared = trait.order;
  const ranked = declared
    ? declared.filter((value) => counts.has(value))
    : [...counts.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([v]) => v);

  const cap = summary.thresholds.max_discrete_categories;
  const kept = ranked.slice(0, cap);
  const slotOf = new Map<string, number>();
  const categories: Category[] = kept.map((value, slot) => {
    slotOf.set(value, slot);
    return {
      value,
      label: value,
      slot,
      count: counts.get(value) ?? 0,
      swatch: palette.swatch(slot),
    };
  });

  let otherCount = 0;
  for (const [value, count] of counts) {
    if (!slotOf.has(value)) otherCount += count;
  }

  return { kind: "discrete", trait, categories, slotOf, otherCount, missingCount };
}

/** Fill color for one record under a scale. */
export function colorOf(
  scale: Scale,
  records: Records,
  row: number,
  raw?: string,
  numeric?: number | null,
): string {
  if (scale.kind === "continuous") {
    const value = numeric !== undefined ? numeric : records.number(scale.trait.id, row);
    if (value === null) return palette.NO_VALUE_COLOR;
    const span = scale.max - scale.min;
    return palette.viridis(span === 0 ? 0.5 : (value - scale.min) / span);
  }
  const value = raw ?? records.text(scale.trait.id, row);
  if (!value) return palette.MISSING_COLOR;
  const slot = scale.slotOf.get(value);
  return slot === undefined ? palette.OTHER_COLOR : palette.CATEGORICAL[slot]!;
}

/** Glyph for one record. Continuous scales use one glyph throughout; the ramp is
 *  already doing the encoding, and varying shape would imply a second variable. */
export function glyphOf(
  scale: Scale,
  records: Records,
  row: number,
  raw?: string,
  numeric?: number | null,
): palette.Glyph {
  if (scale.kind === "continuous") {
    const value = numeric !== undefined ? numeric : records.number(scale.trait.id, row);
    return value === null ? palette.MISSING_GLYPH : "circle";
  }
  const value = raw ?? records.text(scale.trait.id, row);
  if (!value) return palette.MISSING_GLYPH;
  const slot = scale.slotOf.get(value);
  return slot === undefined ? palette.OTHER_GLYPH : palette.GLYPHS[slot]!;
}

/** Legend entries, including the reserved Other and not-recorded buckets when they
 *  hold anything. Identity is never color-alone: each entry carries its glyph and
 *  its label. */
export function legendEntries(scale: Scale): Category[] {
  if (scale.kind === "continuous") return [];
  const entries = [...scale.categories];
  if (scale.otherCount > 0) {
    entries.push({
      value: OTHER,
      label: OTHER,
      slot: scale.categories.length,
      count: scale.otherCount,
      swatch: { color: palette.OTHER_COLOR, glyph: palette.OTHER_GLYPH, filled: true },
    });
  }
  if (scale.missingCount > 0) {
    entries.push({
      value: "",
      label: MISSING,
      slot: -1,
      count: scale.missingCount,
      swatch: { color: palette.MISSING_COLOR, glyph: palette.MISSING_GLYPH, filled: false },
    });
  }
  return entries;
}
