/** Chapter 06: the alignment underneath.
 *
 *  A second component, not another `ChapterSpec` instance, and the reason is worth
 *  stating because the rest of the site works so hard to be one instrument. A mark in
 *  `ui/chapter.ts` is a point: `scatter.nearest` picks by distance inside 14 px and
 *  `within()` gates drawing on the point's position. A raster row is a horizontal
 *  extent. On `all`/P1 a hover would have grabbed an arbitrary member of a 400-row band,
 *  and a record covering exactly the brushed columns would have failed `within()` and
 *  vanished from the mark layer while its raster row stayed painted.
 *
 *  So the hit test, the thumbnail strip and the row ordering are this module's own.
 *  Everything that can be shared still is: the filters, the colour scale, the axis
 *  machinery, `scatter.axesMarkup`, the brush gesture, the pinned-record inspector, and
 *  the DOM skeleton every other figure uses.
 */

import * as categories from "../model/categories.js";
import * as scatter from "./scatter.js";
import { axis, ordinal } from "../model/panel.js";
import {
  AlignmentBlock,
  columnTrack,
  type ColumnTrack,
  type ProfileFile,
} from "../model/alignment.js";
import {
  canDrawLetters,
  drawLetters,
  drawRaster,
  legendEntries,
  type RasterStats,
  type Vocabulary,
} from "./raster.js";
import { divergenceStates, rowCounts } from "../model/alignment.js";
import { identityLines } from "./detail.js";
import type { Records } from "../model/records.js";
import type { Summary } from "../model/types.js";
import type { RowOrder, View, Zoom } from "../model/view.js";
import { byId, esc, num } from "./dom.js";

export const ID = "alignment";

/** Taller than a scatter and wider than the tree gutter needs: a raster wants every
 *  pixel of both, and its vertical axis carries no ticks because a row's place in the
 *  stack is an ordering, not a quantity. */
export const RASTER_PLOT: scatter.Plot = {
  width: 720,
  height: 760,
  left: 30,
  top: 14,
  right: 16,
  bottom: 58,
};
/** The per-column track above the raster, on the same horizontal scale. */
export const TRACK_HEIGHT = 76;

export interface AlignmentState {
  summary: Summary;
  records: Records;
  view: View;
  region: string;
  block: AlignmentBlock;
  profile: ProfileFile;
  vocabulary: Vocabulary;
  scale: categories.Scale;
  /** Raster rows, filtered and ordered, before the row brush. */
  ordered: number[];
  /** The slice of `ordered` the brush is showing. */
  visible: number[];
  /** Rows the shared `restrict` removed, when one is active. */
  restrictedFrom: string | null;
  restrictedOut: number;
  /** A hand-off this figure refused, and the region the source was showing. */
  droppedFrom: { chapter: string; region: string } | null;
  track: ColumnTrack | null;
  stats: RasterStats | null;
  /** True once the brush is narrow enough to draw the alignment as characters. */
  lettered: boolean;
  x: ReturnType<typeof axis> | null;
  zoom: Zoom | null;
  inspected: number;
  held: number | null;
  brush: scatter.Box | null;
  /** Sort keys another chapter supplied, for the two orderings this one cannot
   *  compute alone. Null when that chapter has not loaded. */
  external: Map<number, number> | null;
}

export function regionsFor(summary: Summary): string[] {
  return summary.regions.filter((region) => region.in_alignment).map((region) => region.id);
}

export function resolveRegion(regions: string[], wanted: string): string {
  if (regions.includes(wanted)) return wanted;
  if (regions.includes("P1")) return "P1";
  return regions[0] ?? "";
}

/** Same filters as every other chapter, so a record hidden there is hidden here. */
function passes(state: AlignmentState, record: number): boolean {
  const { view, records } = state;
  if (view.status !== "all" && records.text("curation_status", record) !== view.status) {
    return false;
  }
  if (!view.engineered && records.text("engineered_or_construct", record) === "TRUE") {
    return false;
  }
  return true;
}

/** Row order. Two of the five come from other chapters, because a place in the tree's
 *  ladder and a non-synonymous rate are their measurements, not this figure's. When
 *  that chapter has not loaded, the order falls back to coverage and the note says so
 *  rather than silently showing a different stack than the control claims. */
function orderRows(state: AlignmentState, rows: number[]): number[] {
  const { block, records, view } = state;
  const keyed = rows.map((row) => {
    const record = block.record[row]!;
    let key: number;
    switch (view.order) {
      case "coverage":
        key = -coveredCount(block, row);
        break;
      case "start":
        key = block.first[row]!;
        break;
      case "ladder":
      case "divergence":
        key = state.external?.get(record) ?? Number.POSITIVE_INFINITY;
        break;
      default:
        key = traitKey(state.scale, records, record);
        break;
    }
    return { row, key, accession: records.accession(record) };
  });
  keyed.sort((a, b) => a.key - b.key || a.accession.localeCompare(b.accession));
  return keyed.map((entry) => entry.row);
}

/** Sort key for the default ordering, so rows stack in the same order the legend
 *  lists. Other and not-recorded sort last, after every named category, rather than
 *  landing in the middle of the stack where they would read as a category of their own. */
function traitKey(scale: categories.Scale, records: Records, record: number): number {
  if (scale.kind === "continuous") {
    return records.number(scale.trait.id, record) ?? Number.POSITIVE_INFINITY;
  }
  const value = records.text(scale.trait.id, record);
  if (!value) return Number.MAX_SAFE_INTEGER;
  return scale.slotOf.get(value) ?? Number.MAX_SAFE_INTEGER - 1;
}

function coveredCount(block: AlignmentBlock, row: number): number {
  const cells = block.row(row);
  let total = 0;
  for (let column = block.first[row]!; column <= block.last[row]!; column += 1) {
    const code = cells[column]!;
    if (code >= 1 && code <= 4) total += 1;
  }
  return total;
}

export function buildState(
  summary: Summary,
  records: Records,
  view: View,
  region: string,
  block: AlignmentBlock,
  profile: ProfileFile,
  options: {
    vocabulary: Vocabulary;
    external: Map<number, number> | null;
    restrictTo: Set<number> | null;
    /** Set when a hand-off was refused because the source chapter is on another
     *  region, carrying that region's id so the figure can say which. */
    restrictDroppedFrom: string | null;
    previousHeld: number | null;
  },
): AlignmentState {
  const trait = summary.traits.find((entry) => entry.id === view.trait);
  if (!trait) throw new Error(`unknown trait ${view.trait}`);
  const allRecords = [...block.record];
  const scale = categories.buildScale(summary, records, trait, allRecords, undefined, undefined);

  const state: AlignmentState = {
    summary,
    records,
    view,
    region,
    block,
    profile,
    vocabulary: block.header.coding ? options.vocabulary : "coverage",
    scale,
    ordered: [],
    visible: [],
    restrictedFrom: null,
    restrictedOut: 0,
    droppedFrom:
      options.restrictDroppedFrom && view.restrict
        ? { chapter: view.restrict.from, region: options.restrictDroppedFrom }
        : null,
    track: null,
    stats: null,
    lettered: false,
    x: null,
    zoom: view.zoom,
    inspected: -1,
    held: null,
    brush: null,
    external: options.external,
  };

  let rows: number[] = [];
  let restrictedOut = 0;
  for (let row = 0; row < block.rows; row += 1) {
    if (!passes(state, block.record[row]!)) continue;
    if (options.restrictTo && !options.restrictTo.has(block.record[row]!)) {
      restrictedOut += 1;
      continue;
    }
    rows.push(row);
  }
  state.restrictedOut = restrictedOut;
  state.restrictedFrom = options.restrictTo ? (view.restrict?.from ?? null) : null;
  state.ordered = orderRows(state, rows);

  if (options.previousHeld !== null) {
    const row = block.rowForRecord(options.previousHeld);
    state.held = state.ordered.includes(row) ? row : null;
  }
  return state;
}

/** The visible slice, after the row brush. Recomputed at render rather than at decode:
 *  a filter change must renumber the stack, and assigning positions once at load would
 *  leave holes where the filtered rows used to be. */
function applyBrush(state: AlignmentState): void {
  const total = state.ordered.length;
  if (!state.zoom) {
    state.visible = state.ordered;
    state.x = axis(0, state.block.width, "linear");
    return;
  }
  const lo = Math.max(0, Math.floor(state.zoom.y0));
  const hi = Math.min(total, Math.ceil(state.zoom.y1) + 1);
  state.visible = state.ordered.slice(lo, Math.max(lo + 1, hi));
  state.x = axis(
    Math.max(0, Math.floor(state.zoom.x0)),
    Math.min(state.block.width, Math.ceil(state.zoom.x1)),
    "linear",
  );
}

export function render(state: AlignmentState): void {
  applyBrush(state);
  renderThumbnails(state);

  const canvas = byId<HTMLCanvasElement>(`${ID}-canvas`);
  const colorOf = (row: number) =>
    categories.colorOf(state.scale, state.records, state.block.record[row]!, undefined, undefined);
  const spec = {
    block: state.block,
    rows: state.visible,
    vocabulary: state.vocabulary,
    colorOf,
    x: state.x!,
  };
  state.lettered = canDrawLetters(state.x!.max - state.x!.min, state.visible.length);
  state.stats = state.lettered
    ? drawLetters(canvas, RASTER_PLOT, spec)
    : drawRaster(canvas, RASTER_PLOT, spec);

  const svg = byId<SVGSVGElement>(`${ID}-axes`);
  svg.setAttribute("viewBox", `0 0 ${RASTER_PLOT.width} ${RASTER_PLOT.height}`);
  svg.innerHTML = scatter.axesMarkup(
    { plot: RASTER_PLOT, x: state.x!, y: ordinal(0, Math.max(1, state.visible.length)) },
    state.block.header.coding && state.vocabulary === "divergence"
      ? "Alignment column (codons coloured by what they contributed to figure 01)"
      : "Alignment column",
    "",
  );

  state.track = columnTrack(state.block, state.visible);
  renderTrack(state);
  renderHighlight(state);
  renderLegend(state);
  renderNote(state);
}

/** The thumbnail strip: one coverage profile per region.
 *
 *  Not a miniature raster. Comparing coverage across regions is the comparison this
 *  figure exists to make, and a profile says it more clearly than a shrunken picture
 *  while costing one small array instead of every region's cells.
 */
function renderThumbnails(state: AlignmentState): void {
  const strip = byId(`${ID}-strip`);
  const regions = regionsFor(state.summary);
  if (!strip.dataset.built) {
    strip.innerHTML = regions
      .map((region) => {
        const label = state.summary.regions.find((r) => r.id === region)?.label ?? region;
        return `
          <button type="button" class="thumb" data-region="${esc(region)}"
                  aria-pressed="false" aria-label="Show ${esc(label)}">
            <span class="thumb-label">${esc(label)}</span>
            <svg class="thumb-profile" viewBox="0 0 168 54" preserveAspectRatio="none"
                 aria-hidden="true"></svg>
            <span class="thumb-count" data-count></span>
          </button>`;
      })
      .join("");
    strip.dataset.built = "true";
    strip.style.gridTemplateColumns = `repeat(${regions.length}, minmax(0, 1fr))`;
  }

  for (const button of strip.querySelectorAll<HTMLButtonElement>(".thumb")) {
    const region = button.dataset.region!;
    const profile = state.profile.regions[region];
    button.setAttribute("aria-pressed", String(region === state.region));
    const count = button.querySelector<HTMLElement>("[data-count]")!;
    if (!profile) {
      count.textContent = "—";
      continue;
    }
    const peak = profile.covered.reduce((most, value) => Math.max(most, value), 1);
    count.textContent = `${Math.round((100 * peak) / state.profile.n_rows)}% at best`;
    count.classList.toggle("is-sparse", peak / state.profile.n_rows < 0.3);

    // One point per pixel column of the thumbnail, taking the maximum inside each bin
    // so a narrow well-covered stretch is not averaged out of existence.
    const points: string[] = [];
    const buckets = 168;
    for (let bucket = 0; bucket < buckets; bucket += 1) {
      const lo = Math.floor((bucket * profile.covered.length) / buckets);
      const hi = Math.max(lo + 1, Math.floor(((bucket + 1) * profile.covered.length) / buckets));
      let best = 0;
      for (let i = lo; i < hi && i < profile.covered.length; i += 1) {
        best = Math.max(best, profile.covered[i]!);
      }
      points.push(`${bucket},${(54 - (best / state.profile.n_rows) * 54).toFixed(1)}`);
    }
    button.querySelector("svg")!.innerHTML =
      `<polyline points="0,54 ${points.join(" ")} 167,54" fill="rgb(49 58 68 / 22%)"` +
      ` stroke="currentColor" stroke-width="0.8" vector-effect="non-scaling-stroke"/>`;
  }
}

/** The honest aggregate: every visible row, column by column.
 *
 *  The raster below samples one record per pixel row once rows outnumber pixels. This
 *  does not, which is why it is here — it is where the full population is represented,
 *  and it is the series keyboard traversal walks. */
function renderTrack(state: AlignmentState): void {
  const svg = byId<SVGSVGElement>(`${ID}-track`);
  const width = RASTER_PLOT.width;
  svg.setAttribute("viewBox", `0 0 ${width} ${TRACK_HEIGHT}`);
  const track = state.track!;
  const left = RASTER_PLOT.left;
  const inner = width - left - RASTER_PLOT.right;
  const lo = state.x!.min;
  const span = Math.max(1, state.x!.max - lo);
  const peak = Math.max(1, ...track.covered);

  const buckets = Math.min(inner, 700);
  const covered: string[] = [];
  const differing: string[] = [];
  for (let bucket = 0; bucket < buckets; bucket += 1) {
    const c0 = Math.floor(lo + (bucket * span) / buckets);
    const c1 = Math.max(c0 + 1, Math.floor(lo + ((bucket + 1) * span) / buckets));
    let bestCovered = 0;
    let bestDiffering = 0;
    for (let column = c0; column < c1 && column < track.covered.length; column += 1) {
      bestCovered = Math.max(bestCovered, track.covered[column]!);
      bestDiffering = Math.max(bestDiffering, track.differing[column]!);
    }
    const x = (left + (bucket / buckets) * inner).toFixed(1);
    covered.push(`${x},${(TRACK_HEIGHT - 14 - (bestCovered / peak) * (TRACK_HEIGHT - 20)).toFixed(1)}`);
    differing.push(`${x},${(TRACK_HEIGHT - 14 - (bestDiffering / peak) * (TRACK_HEIGHT - 20)).toFixed(1)}`);
  }

  svg.innerHTML =
    `<polyline points="${covered.join(" ")}" fill="none" stroke="#313A44" stroke-width="1"/>` +
    (state.block.header.coding
      ? `<polyline points="${differing.join(" ")}" fill="none" stroke="#902731" stroke-width="1"/>`
      : "") +
    `<text x="${left}" y="10" class="track-label">${num(peak)} records readable at the best column` +
    (state.block.header.coding ? ` · red: differing from reference` : "") +
    `</text>`;
}

export function renderHighlight(state: AlignmentState): void {
  const overlay = byId<SVGSVGElement>(`${ID}-overlay`);
  overlay.setAttribute("viewBox", `0 0 ${RASTER_PLOT.width} ${RASTER_PLOT.height}`);
  const parts: string[] = [];
  const { w, h } = scatter.inner(RASTER_PLOT);

  for (const [row, klass] of [
    [state.inspected, "raster-hover"],
    [state.held, "raster-held"],
  ] as [number | null, string][]) {
    if (row === null || row < 0) continue;
    const at = state.visible.indexOf(row);
    if (at < 0) continue;
    const y = state.lettered
      ? RASTER_PLOT.top + ((at + 1.5) / (state.visible.length + 1)) * h
      : RASTER_PLOT.top + ((at + 0.5) / state.visible.length) * h;
    parts.push(
      `<line class="${klass}" x1="${RASTER_PLOT.left}" y1="${y.toFixed(1)}" ` +
        `x2="${RASTER_PLOT.left + w}" y2="${y.toFixed(1)}"/>`,
    );
  }
  if (state.brush) {
    const { x0, y0, x1, y1 } = state.brush;
    parts.push(
      `<rect class="brush" x="${Math.min(x0, x1)}" y="${Math.min(y0, y1)}" ` +
        `width="${Math.abs(x1 - x0)}" height="${Math.abs(y1 - y0)}"/>`,
    );
  }
  overlay.innerHTML = parts.join("");
}

function renderLegend(state: AlignmentState): void {
  const target = byId(`${ID}-legend`);
  const entries = legendEntries(state.vocabulary);
  const toggle = state.block.header.coding
    ? `<div class="vocab-toggle">
         <button type="button" data-vocab="coverage"
                 aria-pressed="${state.vocabulary === "coverage"}">Coverage</button>
         <button type="button" data-vocab="divergence"
                 aria-pressed="${state.vocabulary === "divergence"}">Divergence</button>
       </div>`
    : `<p class="legend-missing">A non-coding region carries no reference in any figure,
         so only coverage is shown here.</p>`;

  target.innerHTML =
    `<p class="legend-title">${state.vocabulary === "divergence" ? "Codon" : "Column"}</p>` +
    toggle +
    `<ul class="legend-list">` +
    entries
      .map(
        (entry) =>
          `<li><span class="legend-chip" style="background:${entry.color}"></span>` +
          `<span class="legend-label">${esc(entry.label)}${
            entry.note ? `<small>${esc(entry.note)}</small>` : ""
          }</span></li>`,
      )
      .join("") +
    `</ul>`;
}

function renderNote(state: AlignmentState): void {
  const region = state.summary.regions.find((r) => r.id === state.region);
  const stats = state.stats!;
  const parts: string[] = [];

  parts.push(
    `<strong>${num(state.visible.length)}</strong> sequences over ` +
      `${num(state.block.width)} alignment columns of ${esc(region?.label ?? state.region)}.`,
  );

  // A figure that samples has to say so, in the same breath as its count.
  if (stats.passedOver > 0) {
    parts.push(
      `The panel is ${num(stats.rowsPerPixel < 1 ? 1 : Math.round(stats.rowsPerPixel))}× taller in
       records than in pixels, so each row of pixels draws <strong>one</strong> of them and
       ${num(stats.passedOver)} are not drawn. Every record is still counted in the track above,
       which never samples. Brush a range to reach the rest.`,
    );
  } else {
    parts.push("Every visible record has a row of its own.");
  }

  if (state.lettered) {
    parts.push(
      `Narrow enough to draw the alignment itself: every character is one position of one
       record, with its reference on the line above and codon boundaries ruled. Colour still
       carries the same meaning it did in the binned view.`,
    );
  }
  if (!state.lettered && stats.columnsPerPixel > 1.05) {
    parts.push(
      `Each pixel spans ${stats.columnsPerPixel.toFixed(1)} columns and is painted with the most
       consequential state inside it, so a lone difference stays visible rather than being
       averaged away.`,
    );
  }

  if (state.droppedFrom) {
    const label = state.summary.regions.find((r) => r.id === state.droppedFrom!.region);
    parts.push(
      `A set was handed over from the ${esc(sourceLabel(state.droppedFrom.chapter))} figure, but
       that figure is showing ${esc(label?.label ?? state.droppedFrom.region)} and this one is
       showing ${esc(state.summary.regions.find((r) => r.id === state.region)?.label ?? state.region)}.
       A brushed rectangle only means something on the axes it was drawn on, so it is not applied
       here. <button type="button" class="text-button" data-clear-restrict>Dismiss</button>`,
    );
  }
  if (state.restrictedFrom) {
    // `ordered`, not `visible`: the hand-off supplied this many, and this figure's own
    // brush may then have narrowed them further. Reporting the post-brush count here
    // would credit the other chapter with a selection it did not make.
    parts.push(
      `Restricted to the ${num(state.ordered.length)} records brushed in the
       ${esc(sourceLabel(state.restrictedFrom))} figure; ${num(state.restrictedOut)} others are
       held back. <button type="button" class="text-button" data-clear-restrict>Show all</button>`,
    );
  }
  if (state.zoom) {
    parts.push(
      `<button type="button" class="text-button" data-reset-zoom>Show the whole region</button>`,
    );
  }
  if (
    (state.view.order === "ladder" || state.view.order === "divergence") &&
    !state.external
  ) {
    parts.push(
      `That ordering comes from another figure, which has not loaded for this selection, so the
       rows are stacked by coverage instead.`,
    );
  }
  if (state.vocabulary === "divergence") {
    parts.push(
      `Every codon here is one count in figure 01: the row sums to that record's position in the
       divergence scatter.`,
    );
  }

  byId(`${ID}-note`).innerHTML = parts.filter(Boolean).join(" ");
}

function sourceLabel(id: string): string {
  return (
    {
      divergence: "divergence",
      distance: "nucleotide distance",
      "phylogeny-nt": "nucleotide phylogeny",
      "distance-aa": "protein distance",
      "phylogeny-aa": "protein phylogeny",
    }[id] ?? id
  );
}

/** Rows for the shared pinned-record inspector, so a record pinned anywhere reports what
 *  this figure measured about it too — including the two numbers no other chapter can
 *  state: where in the region the record actually sits, and how much of that span is
 *  material rather than deletion. */
export function measured(state: AlignmentState, rasterRow: number): [string, string][] {
  const block = state.block;
  const first = block.first[rasterRow]!;
  const last = block.last[rasterRow]!;
  if (last < first) return [["Covered span", "nothing in this region"]];

  const cells = block.row(rasterRow);
  let bases = 0;
  let ambiguous = 0;
  let gaps = 0;
  for (let column = first; column <= last; column += 1) {
    const code = cells[column]!;
    if (code >= 1 && code <= 4) bases += 1;
    else if (code === 5) ambiguous += 1;
    else gaps += 1;
  }

  const rows: [string, string][] = [
    ["Covered span", `columns ${num(first + 1)}–${num(last + 1)} of ${num(block.width)}`],
    ["Readable bases", num(bases)],
    ["— ambiguity codes", ambiguous ? num(ambiguous) : "none"],
    ["— gaps inside the span", gaps ? num(gaps) : "none"],
    ["Position in the stack", `${num(state.visible.indexOf(rasterRow) + 1)} of ${num(state.visible.length)}`],
  ];
  const label = block.referenceLabel(rasterRow);
  if (block.header.coding) {
    rows.push(["Measured against", label || "no comparable reference"]);
  }
  return rows;
}

/** The hover readout for one row.
 *
 *  Its own, rather than `renderReadout` with a stand-in `ChapterSpec`: that function
 *  calls `spec.readout`, which this chapter has no honest value for. It shares the three
 *  identity lines every figure opens with and then says alignment things — where the
 *  record sits in the region, and what its row contributes to figure 01. */
export function renderRowReadout(state: AlignmentState, rasterRow: number): void {
  const target = byId(`${ID}-readout`);
  if (rasterRow < 0) {
    target.classList.remove("is-active");
    target.innerHTML =
      `<span class="readout-hint">Hover a row to read it; click to pin every field. Drag a box
       to zoom to a range of columns and rows. Arrow keys walk the track above.</span>`;
    return;
  }
  target.classList.add("is-active");

  const block = state.block;
  const record = block.record[rasterRow]!;
  const first = block.first[rasterRow]!;
  const last = block.last[rasterRow]!;
  const lines = identityLines(state.records, record);

  if (last < first) {
    lines.push(`<span>nothing in this region</span>`);
  } else {
    lines.push(
      `<span>columns <b>${num(first + 1)}</b>–<b>${num(last + 1)}</b> of ${num(block.width)}</span>`,
    );
    if (state.vocabulary === "divergence") {
      const counts = rowCounts(
        divergenceStates(block.row(rasterRow), block.referenceRow(rasterRow), block.width),
      );
      lines.push(
        counts.assessable
          ? `<span><b>${num(counts.synonymous)}</b> syn, <b>${num(counts.nonsynonymous)}</b>
             non-syn over <b>${num(counts.assessable)}</b> codons — this row's sums are its
             point in figure 01</span>`
          : `<span>no comparable reference, so figure 01 reports it unmeasurable</span>`,
      );
    }
  }
  if (state.held !== rasterRow) lines.push('<span class="readout-hint">Click to pin</span>');
  target.innerHTML = lines.join("");
}

// --- Interaction ------------------------------------------------------------

/** The record under a pointer.
 *
 *  Its own hit test rather than `scatter.nearest`: a raster row spans the panel, so
 *  vertical position alone identifies it, and the sampled row is the one actually drawn
 *  rather than a neighbour standing in for it. */
export function rowAt(state: AlignmentState, clientX: number, clientY: number): number {
  const canvas = byId<HTMLCanvasElement>(`${ID}-canvas`);
  const rect = canvas.getBoundingClientRect();
  const scale = RASTER_PLOT.width / rect.width;
  const y = (clientY - rect.top) * scale;
  const { h } = scatter.inner(RASTER_PLOT);
  const fraction = (y - RASTER_PLOT.top) / h;
  if (fraction < 0 || fraction >= 1 || !state.visible.length) return -1;
  void clientX;
  // A lettered panel spends its first lane on the reference row, so the record lanes are
  // shifted by one and a pointer in that first lane belongs to no record.
  if (state.lettered) {
    const lanes = state.visible.length + 1;
    const lane = Math.floor(fraction * lanes) - 1;
    return lane < 0 ? -1 : state.visible[Math.min(state.visible.length - 1, lane)]!;
  }
  return state.visible[Math.min(state.visible.length - 1, Math.floor(fraction * state.visible.length))]!;
}

export function positionAt(
  clientX: number,
  clientY: number,
): [number, number] {
  const canvas = byId<HTMLCanvasElement>(`${ID}-canvas`);
  const rect = canvas.getBoundingClientRect();
  const scale = RASTER_PLOT.width / rect.width;
  return [(clientX - rect.left) * scale, (clientY - rect.top) * scale];
}

/** A dragged rectangle as a column range and a row range. */
export function boxToZoom(state: AlignmentState, box: scatter.Box): Zoom | null {
  const { w, h } = scatter.inner(RASTER_PLOT);
  const toColumn = (x: number) =>
    state.x!.min + ((x - RASTER_PLOT.left) / w) * (state.x!.max - state.x!.min);
  const toRow = (y: number) => ((y - RASTER_PLOT.top) / h) * state.visible.length;

  const x0 = Math.min(toColumn(box.x0), toColumn(box.x1));
  const x1 = Math.max(toColumn(box.x0), toColumn(box.x1));
  const yLo = Math.min(toRow(box.y0), toRow(box.y1));
  const yHi = Math.max(toRow(box.y0), toRow(box.y1));
  if (!(x1 > x0 + 1) || !(yHi > yLo)) return null;

  // Row indices are positions in the CURRENT visible slice; convert to positions in the
  // full ordering so a second brush composes with the first instead of resetting it.
  const offset = state.ordered.indexOf(state.visible[0] ?? -1);
  const base = offset < 0 ? 0 : offset;
  return {
    x0,
    x1,
    y0: base + Math.max(0, Math.floor(yLo)),
    y1: base + Math.min(state.visible.length, Math.ceil(yHi)),
  };
}

/** Keyboard traversal walks the COLUMN TRACK, not the rows.
 *
 *  Every other figure lets arrows step mark to mark, and for 24,305 rows that is 24,305
 *  presses to cross a panel whose content is `aria-hidden` pixels. The track is a real
 *  one-dimensional series with a describable value at every column — how many records
 *  are readable there, and how many differ — so it is the axis a keyboard reader can
 *  actually use. Rows stay reachable: brush to a handful and they become steppable.
 */
export function columnStep(state: AlignmentState, current: number, delta: number): number {
  const lo = Math.floor(state.x!.min);
  const hi = Math.ceil(state.x!.max) - 1;
  if (current < lo || current > hi) return delta > 0 ? lo : hi;
  return Math.max(lo, Math.min(hi, current + delta));
}
