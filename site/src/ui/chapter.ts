/** One figure chapter: a strip of live region thumbnails above one focus panel.
 *
 *  Both figure sets get the same instrument — same thumbnail strip, same legend, same
 *  hover and keyboard traversal, same click-to-pin, same brush-to-zoom — because they
 *  answer the same kind of question about the same records, and a reader should not
 *  have to relearn the controls between them. What differs is where the marks come
 *  from and what a readout says about one, which is the whole of `ChapterSpec`.
 *
 *  Thumbnails rather than tabs: the regions hold different populations, and that
 *  comparison is most of the diagnostic value. A tab bar costs the same vertical space
 *  and hides it.
 */

import * as categories from "../model/categories.js";
import * as palette from "../model/palette.js";
import * as scatter from "./scatter.js";
import type { Axis, PanelFile } from "../model/panel.js";
import { axis, zoomed } from "../model/panel.js";
import { type Mark, type MarkSet, markExtent } from "../model/mark.js";
import type { Records } from "../model/records.js";
import type { Summary, Trait } from "../model/types.js";
import type { AxisScale, View, Zoom } from "../model/view.js";
import { pickSelection } from "../model/view.js";
import { byId, esc, num } from "./dom.js";

export interface ChapterSpec {
  /** Matches the element id prefix in index.html, and the region catalog flag. */
  id: string;
  regionFlag: "in_divergence" | "in_distance";
  xLabel: string;
  yLabel: string;
  /** False for a chapter whose coordinates are signed, where a square root has no
   *  meaning; such a chapter is drawn linear whatever the control says. */
  honoursScale: boolean;
  /** Decode one region of a panel file into marks plus the facts the note states.
   *  Takes the scale because for one chapter it selects the axis transform and for the
   *  other it selects which embedding to show. */
  marks: (file: PanelFile, region: string, scale: AxisScale) => MarkSet;
  /** Lines for the compact hover readout, after the shared identity lines. */
  readout: (records: Records, set: MarkSet, mark: Mark) => string[];
  /** Rows for the pinned detail's "measured in this panel" list. */
  measured: (set: MarkSet, mark: Mark) => [string, string][];
}

export interface ChapterState {
  spec: ChapterSpec;
  summary: Summary;
  records: Records;
  view: View;
  file: PanelFile;
  regions: string[];
  /** The region this chapter is actually showing. Not always `view.region`: the two
   *  chapters cover different region sets — the polyprotein exists only in divergence,
   *  the two non-coding regions only in distance — so a single shared value cannot be
   *  valid for both. It is shared where it can be, which is P1, P2 and P3. */
  region: string;
  sets: Map<string, MarkSet>;
  scale: categories.Scale;
  inspected: Mark | null;
  held: Mark | null;
  frame: scatter.Frame | null;
  visibleMarks: Mark[];
  brush: scatter.Box | null;
}

const cache = new Map<string, PanelFile>();

export async function loadPanels(selection: string): Promise<PanelFile> {
  const existing = cache.get(selection);
  if (existing) return existing;
  const response = await fetch(`data/panels/${selection}.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`panels/${selection}.json: HTTP ${response.status}`);
  const file = (await response.json()) as PanelFile;
  cache.set(selection, file);
  return file;
}

/** `type_concordance` is not a stored column: it is the curated virus_type judged
 *  against the alignment the record was placed in, so it depends on the selection. */
export function concordanceValue(
  summary: Summary,
  records: Records,
  view: View,
): ((row: number) => string) | undefined {
  if (view.trait !== "type_concordance") return undefined;
  const selection = pickSelection(summary, view.selection);
  const isSerotype = /^PV[123]$/.test(selection.id);
  return (row: number) => {
    if (!isSerotype) return "concordant";
    return records.text("virus_type", row) === selection.id ? "concordant" : "discordant";
  };
}

export function buildState(
  spec: ChapterSpec,
  summary: Summary,
  records: Records,
  view: View,
  file: PanelFile,
  previousHeld: number | null,
): ChapterState {
  const regions = summary.regions.filter((r) => r[spec.regionFlag]).map((r) => r.id);
  const sets = new Map(
    regions.map((region) => [region, spec.marks(file, region, view.scale)]),
  );
  const region = resolveRegion(regions, view.region);

  const trait = summary.traits.find((entry) => entry.id === view.trait);
  if (!trait) throw new Error(`unknown trait ${view.trait}`);

  // Built over the whole selection, not the current region and not the filtered
  // subset, so a colour means the same thing in every panel of every chapter and does
  // not move when a filter changes.
  const allRows = new Set<number>();
  for (const set of sets.values()) for (const mark of set.marks) allRows.add(mark.record);
  const scale = categories.buildScale(
    summary,
    records,
    trait,
    [...allRows],
    concordanceValue(summary, records, view),
  );

  const state: ChapterState = {
    spec,
    summary,
    records,
    view,
    file,
    regions,
    region,
    sets,
    scale,
    inspected: null,
    held: null,
    frame: null,
    visibleMarks: [],
    brush: null,
  };
  if (previousHeld !== null) {
    state.held = visible(state, currentSet(state)).find((m) => m.record === previousHeld) ?? null;
  }
  return state;
}

/** The shared region if this chapter has it, else its own most-populated fallback —
 *  P1, which every selection fills completely because a record enters an alignment by
 *  capsid typing. */
export function resolveRegion(regions: string[], wanted: string): string {
  if (regions.includes(wanted)) return wanted;
  if (regions.includes("P1")) return "P1";
  return regions[0] ?? "";
}

export function currentSet(state: ChapterState): MarkSet {
  return state.sets.get(state.region) ?? { marks: [], facts: emptyFacts() };
}

function emptyFacts() {
  return { region: "", total: 0, minNt: 0, columns: 0, excludedBelowCoverage: 0, notes: [] };
}

/** Filters change which marks are drawn; they never change the colour assignment, so
 *  surviving categories keep their hues. */
function passes(state: ChapterState, record: number): boolean {
  const { view, records } = state;
  if (view.status !== "all" && records.text("curation_status", record) !== view.status) {
    return false;
  }
  if (!view.engineered && records.text("engineered_or_construct", record) === "TRUE") {
    return false;
  }
  return true;
}

function visible(state: ChapterState, set: MarkSet): Mark[] {
  return set.marks.filter((mark) => passes(state, mark.record));
}

/** The scale the AXES are drawn on. A chapter whose coordinates are signed has no real
 *  square root to draw, so its axes stay linear even when the control says otherwise —
 *  there, the control has already done its work on the distances themselves. */
function effectiveScale(state: ChapterState): AxisScale {
  return state.spec.honoursScale ? state.view.scale : "linear";
}

function styleOf(state: ChapterState) {
  const raw = concordanceValue(state.summary, state.records, state.view);
  return (mark: Mark): scatter.MarkStyle => ({
    color: categories.colorOf(state.scale, state.records, mark.record, raw?.(mark.record)),
    glyph: categories.glyphOf(state.scale, state.records, mark.record, raw?.(mark.record)),
  });
}

export function render(state: ChapterState): void {
  const style = styleOf(state);
  const scale = effectiveScale(state);
  renderThumbnails(state, style, scale);

  const set = currentSet(state);
  const marks = visible(state, set);
  state.visibleMarks = marks;

  // Every panel snaps to its own data, recomputed on region, colour and filter
  // changes: absolute values differ by segment, so a shared range would compress most
  // panels to serve a comparison that is not the one being made.
  const own = markExtent(marks, scale, axis);
  const range = state.view.zoom ? zoomed(state.view.zoom, scale) : own;
  const frame: scatter.Frame = { plot: scatter.FOCUS_PLOT, x: range.x, y: range.y };
  state.frame = frame;

  const svg = byId<SVGSVGElement>(`${state.spec.id}-axes`);
  svg.setAttribute("viewBox", `0 0 ${frame.plot.width} ${frame.plot.height}`);
  svg.innerHTML = scatter.axesMarkup(frame, state.spec.xLabel, state.spec.yLabel);

  scatter.drawMarks(byId<HTMLCanvasElement>(`${state.spec.id}-canvas`), frame, marks, style, {
    radius: scatter.radiusFor(marks.length),
    markFlagged: true,
  });

  renderHighlight(state);
  renderLegend(state, marks);
  renderNote(state, set, marks);
}

function renderThumbnails(
  state: ChapterState,
  style: (mark: Mark) => scatter.MarkStyle,
  scale: AxisScale,
): void {
  const strip = byId(`${state.spec.id}-strip`);
  if (!strip.dataset.built) {
    strip.innerHTML = state.regions
      .map((region) => {
        const label = state.summary.regions.find((r) => r.id === region)?.label ?? region;
        return `
          <button type="button" class="thumb" data-region="${esc(region)}"
                  aria-pressed="false" aria-label="Show ${esc(label)}">
            <span class="thumb-label">${esc(label)}</span>
            <canvas class="thumb-canvas" aria-hidden="true"></canvas>
            <span class="thumb-count" data-count></span>
          </button>`;
      })
      .join("");
    strip.dataset.built = "true";
    strip.style.gridTemplateColumns = `repeat(${state.regions.length}, minmax(0, 1fr))`;
  }

  for (const button of strip.querySelectorAll<HTMLButtonElement>(".thumb")) {
    const region = button.dataset.region!;
    const set = state.sets.get(region);
    const marks = set ? visible(state, set) : [];
    button.setAttribute("aria-pressed", String(region === state.region));
    const count = button.querySelector<HTMLElement>("[data-count]")!;
    count.textContent = num(marks.length);
    count.classList.toggle("is-sparse", marks.length < 500);

    // Each thumbnail carries its own range and does not print it. At this size the
    // comparison a reader can make is shape, which stays fair across ranges; the
    // focus panel's labelled axes are where the numbers live.
    const own = markExtent(marks, scale, axis);
    scatter.drawMarks(
      button.querySelector<HTMLCanvasElement>("canvas")!,
      { plot: scatter.THUMB_PLOT, x: own.x, y: own.y },
      marks,
      style,
      { radius: scatter.radiusFor(marks.length, true), markFlagged: false },
    );
  }
}

export function renderHighlight(state: ChapterState): void {
  const frame = state.frame;
  if (!frame) return;
  const overlay = byId<SVGSVGElement>(`${state.spec.id}-overlay`);
  overlay.setAttribute("viewBox", `0 0 ${frame.plot.width} ${frame.plot.height}`);
  const radius = scatter.radiusFor(state.visibleMarks.length);
  overlay.innerHTML =
    scatter.highlightMarkup(frame, state.inspected, state.held, radius) +
    scatter.brushMarkup(frame, state.brush);
}

function glyphSvg(swatch: palette.Swatch): string {
  const attrs = swatch.filled
    ? `fill="${swatch.color}" stroke="none"`
    : `fill="none" stroke="${swatch.color}" stroke-width="1.6"`;
  const body =
    swatch.glyph === "square" || swatch.glyph === "openSquare"
      ? `<rect x="3" y="3" width="10" height="10" ${attrs}/>`
      : swatch.glyph === "triangle"
        ? `<polygon points="8,2 14,13 2,13" ${attrs}/>`
        : swatch.glyph === "down"
          ? `<polygon points="8,14 14,3 2,3" ${attrs}/>`
          : swatch.glyph === "diamond"
            ? `<polygon points="8,1 15,8 8,15 1,8" ${attrs}/>`
            : `<circle cx="8" cy="8" r="5" ${attrs}/>`;
  return `<svg class="legend-glyph" viewBox="0 0 16 16" aria-hidden="true">${body}</svg>`;
}

/** A circle with a cross through it, matching what the canvas draws over a flagged
 *  mark. The legend has to carry this: an unexplained annotation on one dot reads as a
 *  rendering artifact rather than as a warning. */
const CROSS_GLYPH =
  `<svg class="legend-glyph" viewBox="0 0 16 16" aria-hidden="true">` +
  `<circle cx="8" cy="8" r="4" fill="none" stroke="currentColor" stroke-width="1.4"/>` +
  `<path d="M2 2 L14 14 M14 2 L2 14" fill="none" stroke="currentColor" stroke-width="1.4"/>` +
  `</svg>`;

function renderLegend(state: ChapterState, marks: Mark[]): void {
  const target = byId(`${state.spec.id}-legend`);
  const thin = marks.filter((mark) => mark.weight < 1).length;
  const flagged = marks.filter((mark) => mark.flagged).length;
  const footnote =
    (thin
      ? `<p class="legend-missing">${num(thin)} drawn smaller: their position rests on
           thin overlap and carries less weight.</p>`
      : "") +
    (flagged
      ? `<p class="legend-missing">${CROSS_GLYPH} ${num(flagged)} crossed: a frameshifting
           indel, so the protein downstream of it does not translate as written and the
           non-synonymous count is not trustworthy.</p>`
      : "");

  if (state.scale.kind === "continuous") {
    const stops = [...Array(24).keys()]
      .map((i) => `<span style="background:${palette.viridis(i / 23)}"></span>`)
      .join("");
    const fmt = (value: number) =>
      state.scale.trait.id === "collection_year" ? value.toFixed(1) : num(Math.round(value));
    target.innerHTML = `
      <p class="legend-title">${esc(state.scale.trait.label)}</p>
      <div class="ramp">${stops}</div>
      <div class="ramp-ends"><span>${fmt(state.scale.min)}</span><span>${fmt(state.scale.max)}</span></div>
      ${
        state.scale.missingCount
          ? `<p class="legend-missing">${num(state.scale.missingCount)} with no recorded
               value, drawn grey</p>`
          : ""
      }${footnote}`;
    return;
  }

  target.innerHTML = `
    <p class="legend-title">${esc(state.scale.trait.label)}</p>
    <ul class="legend-list">
      ${categories
        .legendEntries(state.scale)
        .map(
          (entry) => `<li>${glyphSvg(entry.swatch)}<span class="legend-label">${esc(
            entry.label,
          )}</span><span class="legend-count">${num(entry.count)}</span></li>`,
        )
        .join("")}
    </ul>${footnote}`;
}

function renderNote(state: ChapterState, set: MarkSet, marks: Mark[]): void {
  const region = state.summary.regions.find((r) => r.id === state.region);
  const frame = state.frame;
  const inRange = frame
    ? marks.filter((mark) => scatter.within(frame, mark.x, mark.y)).length
    : marks.length;
  const hidden = set.marks.length - marks.length;

  const parts = [
    state.view.zoom
      ? `<strong>${num(inRange)}</strong> of ${num(marks.length)} sequences inside the brushed
         range. <button type="button" class="text-button" data-reset-zoom>Show all</button>`
      : "",
    `<strong>${num(marks.length)}</strong> sequences with at least ${set.facts.minNt} nt in
     ${esc(region?.label ?? state.region)}, across ${num(set.facts.columns)} alignment
     columns.`,
    set.facts.excludedBelowCoverage
      ? `${num(set.facts.excludedBelowCoverage)} fall below that floor and are not drawn.`
      : "",
    hidden > 0 ? `${num(hidden)} more are hidden by the current filters.` : "",
    ...set.facts.notes,
  ];
  byId(`${state.spec.id}-note`).innerHTML = parts.filter(Boolean).join(" ");
}

// --- Interaction ------------------------------------------------------------

export function markAt(state: ChapterState, clientX: number, clientY: number): Mark | null {
  if (!state.frame) return null;
  const canvas = byId<HTMLCanvasElement>(`${state.spec.id}-canvas`);
  const [px, py] = scatter.plotPosition(canvas, state.frame, clientX, clientY);
  return scatter.nearest(state.frame, state.visibleMarks, px, py);
}

export function positionAt(
  state: ChapterState,
  clientX: number,
  clientY: number,
): [number, number] | null {
  if (!state.frame) return null;
  const canvas = byId<HTMLCanvasElement>(`${state.spec.id}-canvas`);
  return scatter.plotPosition(canvas, state.frame, clientX, clientY);
}

/** A dragged rectangle as an axis range, rejected if it is too small to be deliberate
 *  or holds nothing — an empty box is a slip, not an instruction. */
export function boxToZoom(state: ChapterState, box: scatter.Box): Zoom | null {
  const frame = state.frame;
  if (!frame) return null;
  const [ax, ay] = scatter.toData(frame, box.x0, box.y0);
  const [bx, by] = scatter.toData(frame, box.x1, box.y1);
  const zoom = {
    x0: Math.min(ax, bx),
    x1: Math.max(ax, bx),
    y0: Math.min(ay, by),
    y1: Math.max(ay, by),
  };
  if (!(zoom.x1 > zoom.x0) || !(zoom.y1 > zoom.y0)) return null;
  const holds = state.visibleMarks.some(
    (mark) =>
      mark.x >= zoom.x0 && mark.x <= zoom.x1 && mark.y >= zoom.y0 && mark.y <= zoom.y1,
  );
  return holds ? zoom : null;
}

/** Ordered for keyboard traversal: by x then y, so arrows walk the cloud in a
 *  predictable direction rather than in file order. */
export function ordered(state: ChapterState): Mark[] {
  return [...state.visibleMarks].sort((a, b) => a.x - b.x || a.y - b.y);
}

export function traitOf(state: ChapterState): Trait {
  return state.scale.trait;
}

export function axisOf(state: ChapterState): { x: Axis; y: Axis } | null {
  return state.frame ? { x: state.frame.x, y: state.frame.y } : null;
}
