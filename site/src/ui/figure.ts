/** The divergence chapter: a strip of live region thumbnails above one focus panel.
 *
 *  Thumbnails rather than tabs, because the four regions are four different
 *  populations — PV1 holds 3,732 sequences in P1 and 423 in P3 — and that
 *  comparison is most of the diagnostic value. A tab bar costs the same vertical
 *  space and hides it.
 */

import * as categories from "../model/categories.js";
import * as palette from "../model/palette.js";
import * as scatter from "./scatter.js";
import type { Axis, Panel, PanelFile, Point } from "../model/panel.js";
import { assertPanelSchema, decodeRegion, extent, zoomed } from "../model/panel.js";
import type { Records } from "../model/records.js";
import type { Summary, Trait } from "../model/types.js";
import type { View, Zoom } from "../model/view.js";
import { pickSelection } from "../model/view.js";
import { byId, esc, num } from "./dom.js";

const X_LABEL = "Synonymous differences per codon compared";
const Y_LABEL = "Non-synonymous per codon compared";

const cache = new Map<string, PanelFile>();

export async function loadPanels(selection: string): Promise<PanelFile> {
  const existing = cache.get(selection);
  if (existing) return existing;
  const response = await fetch(`data/panels/${selection}.json`, { cache: "no-cache" });
  if (!response.ok) throw new Error(`panels/${selection}.json: HTTP ${response.status}`);
  const file = assertPanelSchema((await response.json()) as PanelFile);
  cache.set(selection, file);
  return file;
}

export interface FigureState {
  summary: Summary;
  records: Records;
  view: View;
  file: PanelFile;
  regions: string[];
  panels: Map<string, Panel>;
  scale: categories.Scale;
  inspected: Point | null;
  held: Point | null;
}

/** Records excluded by the filter row. Filters change which marks are drawn; they
 *  never change the color assignment, so surviving categories keep their hues. */
function passesFilters(state: FigureState, record: number): boolean {
  const { view, records } = state;
  if (view.status !== "all" && records.text("curation_status", record) !== view.status) {
    return false;
  }
  if (!view.engineered && records.text("engineered_or_construct", record) === "TRUE") {
    return false;
  }
  return true;
}

function visible(state: FigureState, panel: Panel): Panel {
  const points = panel.points.filter((point) => passesFilters(state, point.record));
  return points.length === panel.points.length ? panel : { ...panel, points };
}

export function buildState(
  summary: Summary,
  records: Records,
  view: View,
  file: PanelFile,
): FigureState {
  const regions = summary.regions.filter((r) => r.in_divergence).map((r) => r.id);
  const panels = new Map(regions.map((region) => [region, decodeRegion(file, region)]));

  const trait = summary.traits.find((entry) => entry.id === view.trait);
  if (!trait) throw new Error(`unknown trait ${view.trait}`);

  // The scale is built over the whole selection, not the current region and not the
  // filtered subset, so a colour means the same thing across all four panels and
  // does not move when a filter changes.
  const allRows = new Set<number>();
  for (const panel of panels.values()) {
    for (const point of panel.points) allRows.add(point.record);
  }
  const scale = categories.buildScale(
    summary,
    records,
    trait,
    [...allRows],
    concordanceValue(summary, records, view),
  );

  return {
    summary,
    records,
    view,
    file,
    regions,
    panels,
    scale,
    inspected: null,
    held: null,
  };
}

/** `type_concordance` is not a stored column: it is the curated virus_type judged
 *  against the alignment the record was placed in, so it depends on the selection. */
function concordanceValue(
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

function styleOf(state: FigureState) {
  const raw = concordanceValue(state.summary, state.records, state.view);
  return (point: Point): scatter.MarkStyle => ({
    color: categories.colorOf(state.scale, state.records, point.record, raw?.(point.record)),
    glyph: categories.glyphOf(state.scale, state.records, point.record, raw?.(point.record)),
  });
}

export function render(state: FigureState): void {
  const focusPanel = visible(state, state.panels.get(state.view.region) ?? emptyPanel());
  // Every panel snaps to its own data, recomputed whenever the region, the colour or
  // a filter changes. See the note on `extent` for why this beats a shared range.
  const style = styleOf(state);

  renderThumbnails(state, style);
  renderFocus(state, focusPanel, extent(focusPanel, state.view.scale), style);
  renderLegend(state);
  renderFigureNote(state, focusPanel);
}

function emptyPanel(): Panel {
  return {
    region: "",
    points: [],
    references: [],
    excluded: { below_coverage: 0, no_reference: 0 },
    codons: 0,
    minNt: 0,
  };
}

function renderThumbnails(
  state: FigureState,
  style: (point: Point) => scatter.MarkStyle,
): void {
  const strip = byId("divergence-strip");
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
  }

  for (const button of strip.querySelectorAll<HTMLButtonElement>(".thumb")) {
    const region = button.dataset.region!;
    const panel = visible(state, state.panels.get(region) ?? emptyPanel());
    button.setAttribute("aria-pressed", String(region === state.view.region));
    // Each thumbnail carries its own range and does not print it. At this size the
    // comparison a reader can actually make is shape, and shape stays a fair
    // comparison across differing ranges; the focus panel's labelled axes are where
    // the numbers live.
    const own = extent(panel, state.view.scale);
    const count = button.querySelector<HTMLElement>("[data-count]")!;
    count.textContent = num(panel.points.length);
    count.classList.toggle("is-sparse", panel.points.length < 500);

    const canvas = button.querySelector<HTMLCanvasElement>("canvas")!;
    const frame = { plot: scatter.THUMB_PLOT, x: own.x, y: own.y };
    scatter.drawMarks(canvas, frame, panel, style, {
      radius: scatter.radiusFor(panel.points.length, true),
      markFrameshift: false,
    });
  }
}

let focusFrame: scatter.Frame | null = null;
let focusPanelRef: Panel | null = null;

function renderFocus(
  state: FigureState,
  panel: Panel,
  own: { x: Axis; y: Axis },
  style: (point: Point) => scatter.MarkStyle,
): void {
  // The focus panel honours a brushed range; the thumbnails deliberately do not, so
  // the strip keeps showing each region's whole cloud as context.
  const range = state.view.zoom ? zoomed(state.view.zoom, state.view.scale) : own;
  const frame: scatter.Frame = { plot: scatter.FOCUS_PLOT, x: range.x, y: range.y };
  focusFrame = frame;
  focusPanelRef = panel;

  const svg = byId<SVGSVGElement>("divergence-axes");
  svg.setAttribute("viewBox", `0 0 ${frame.plot.width} ${frame.plot.height}`);
  svg.innerHTML = scatter.axesMarkup(frame, X_LABEL, Y_LABEL);

  const canvas = byId<HTMLCanvasElement>("divergence-canvas");
  scatter.drawMarks(canvas, frame, panel, style, {
    radius: scatter.radiusFor(panel.points.length),
    markFrameshift: true,
  });

  renderHighlight(state);
}

let brushBox: scatter.Box | null = null;

export function setBrush(box: scatter.Box | null): void {
  brushBox = box;
}

export function currentFrame(): scatter.Frame | null {
  return focusFrame;
}

export function renderHighlight(state: FigureState): void {
  if (!focusFrame) return;
  const overlay = byId<SVGSVGElement>("divergence-overlay");
  overlay.setAttribute("viewBox", `0 0 ${focusFrame.plot.width} ${focusFrame.plot.height}`);
  const radius = scatter.radiusFor(focusPanelRef?.points.length ?? 0);
  overlay.innerHTML =
    scatter.highlightMarkup(focusFrame, state.inspected, state.held, radius) +
    scatter.brushMarkup(focusFrame, brushBox);
}

function glyphSvg(swatch: palette.Swatch): string {
  const filled = swatch.filled;
  const attrs = filled
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

function renderLegend(state: FigureState): void {
  const target = byId("divergence-legend");
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
          ? `<p class="legend-missing">${glyphSvg({
              color: palette.MISSING_COLOR,
              glyph: palette.MISSING_GLYPH,
              filled: false,
            })} ${num(state.scale.missingCount)} with no recorded value, drawn unfilled</p>`
          : ""
      }`;
    return;
  }

  const entries = categories.legendEntries(state.scale);
  target.innerHTML = `
    <p class="legend-title">${esc(state.scale.trait.label)}</p>
    <ul class="legend-list">
      ${entries
        .map(
          (entry) => `<li>${glyphSvg(entry.swatch)}<span class="legend-label">${esc(
            entry.label,
          )}</span><span class="legend-count">${num(entry.count)}</span></li>`,
        )
        .join("")}
    </ul>`;
}

function renderFigureNote(state: FigureState, panel: Panel): void {
  const region = state.summary.regions.find((r) => r.id === state.view.region);
  const full = state.panels.get(state.view.region);
  const filtered = (full?.points.length ?? 0) - panel.points.length;
  const references = panel.references.length;
  const shifted = panel.points.filter((point) => point.frameshift).length;

  const frame = focusFrame;
  const inRange = frame
    ? panel.points.filter((point) => scatter.within(frame, point.jx, point.jy)).length
    : panel.points.length;
  const parts = [
    state.view.zoom
      ? `<strong>${num(inRange)}</strong> of ${num(panel.points.length)} sequences inside the ` +
        `brushed range. <button type="button" class="text-button" id="reset-zoom">Show all` +
        `</button>`
      : "",
    `<strong>${num(panel.points.length)}</strong> sequences with at least ${
      panel.minNt
    } nt comparable in ${esc(region?.label ?? state.view.region)}, of ${num(panel.codons)} codons.`,
  ];
  if (panel.excluded.below_coverage) {
    parts.push(`${num(panel.excluded.below_coverage)} fall below that floor and are not drawn.`);
  }
  if (panel.excluded.no_reference) {
    parts.push(
      `${num(panel.excluded.no_reference)} have no comparable reference — their virus type is ` +
        `unrecorded or holds too few sequences to support a consensus — so they are reported ` +
        `unmeasurable here rather than compared to a broader consensus that would not mean the ` +
        `same thing. They still appear in the reference-free views.`,
    );
  }
  if (filtered > 0) parts.push(`${num(filtered)} more are hidden by the current filters.`);
  parts.push(
    references === 1
      ? `Measured against ${esc(panel.references[0]?.label ?? "reference")}.`
      : `Measured against ${num(references)} references — Sabin for poliovirus, a consensus of the record's own virus type otherwise.`,
  );
  if (shifted) {
    parts.push(
      shifted === 1
        ? "One carries a frameshifting indel and is crossed rather than trusted downstream of it."
        : `${num(shifted)} carry a frameshifting indel and are crossed rather than trusted downstream of it.`,
    );
  }
  byId("divergence-note").innerHTML = parts.filter(Boolean).join(" ");
}

// --- Interaction ------------------------------------------------------------

export function pointAt(state: FigureState, clientX: number, clientY: number): Point | null {
  if (!focusFrame || !focusPanelRef) return null;
  const canvas = byId<HTMLCanvasElement>("divergence-canvas");
  const [px, py] = scatter.plotPosition(canvas, focusFrame, clientX, clientY);
  return scatter.nearest(focusFrame, focusPanelRef, px, py);
}

/** Plot-space position of a pointer event on the focus canvas. */
export function positionAt(clientX: number, clientY: number): [number, number] | null {
  if (!focusFrame) return null;
  const canvas = byId<HTMLCanvasElement>("divergence-canvas");
  return scatter.plotPosition(canvas, focusFrame, clientX, clientY);
}

/** Turn a dragged plot-space rectangle into an axis range, clamped to the frame and
 *  rejected if it is too small to be a deliberate gesture or holds nothing. */
export function boxToZoom(state: FigureState, box: scatter.Box): Zoom | null {
  if (!focusFrame || !focusPanelRef) return null;
  const [ax, ay] = scatter.toData(focusFrame, box.x0, box.y0);
  const [bx, by] = scatter.toData(focusFrame, box.x1, box.y1);
  const zoom = {
    x0: Math.max(0, Math.min(ax, bx)),
    x1: Math.max(ax, bx),
    y0: Math.max(0, Math.min(ay, by)),
    y1: Math.max(ay, by),
  };
  if (!(zoom.x1 > zoom.x0) || !(zoom.y1 > zoom.y0)) return null;
  const holds = focusPanelRef.points.some(
    (point) =>
      point.jx >= zoom.x0 && point.jx <= zoom.x1 && point.jy >= zoom.y0 && point.jy <= zoom.y1,
  );
  return holds ? zoom : null;
}

/** Ordered points for keyboard traversal: by x then y, so arrow keys walk the cloud
 *  in a predictable direction rather than in file order. */
export function ordered(state: FigureState): Point[] {
  const panel = visible(state, state.panels.get(state.view.region) ?? emptyPanel());
  return [...panel.points].sort((a, b) => a.jx - b.jx || a.jy - b.jy);
}
