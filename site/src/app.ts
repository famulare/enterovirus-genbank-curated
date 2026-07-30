/** Mount. Loads the built artifacts, renders the chrome and both figure chapters, and
 *  keeps the URL hash and the control DOM in step with each other.
 *
 *  One selection state drives every chapter, so a colour, a filter or a region chosen
 *  once applies everywhere and a record noticed in one figure is findable in the next.
 *  Brushing is the exception: a zoom belongs to the figure it was drawn on, so it is
 *  tracked per chapter rather than in the shared view. */

import { assertSchema, type Summary } from "./model/types.js";
import {
  decode,
  defaultView,
  encode,
  sameView,
  traitAfterSelectionChange,
  type View,
  type Zoom,
} from "./model/view.js";
import { Records, type RecordTable } from "./model/records.js";
import { assertPanelSchema } from "./model/panel.js";
import type { Mark } from "./model/mark.js";
import { DISTANCE, DIVERGENCE } from "./model/specs.js";
import * as chapter from "./ui/chapter.js";
import {
  onControlEdit,
  readControls,
  renderControls,
  renderNotes,
  renderStatus,
  syncControls,
} from "./ui/controls.js";
import {
  renderBuildLine,
  renderDataQuality,
  renderFacts,
  renderIntegrityNotes,
  renderPopulationTable,
  renderRawDate,
  renderReleaseBand,
} from "./ui/report.js";
import {
  renderPinned,
  renderReadout,
  type DerivedField,
  type PinnedPanel,
} from "./ui/detail.js";
import { byId } from "./ui/dom.js";

interface Manifest {
  build_identity: string;
}

const SPECS = [DIVERGENCE, DISTANCE];

let summary: Summary;
let records: Records;
let view: View;
let rejected: string[] = [];
let writingHash = false;

/** Per-chapter runtime state. `zoom` lives here, not in the shared view, because a
 *  brushed range means something only on the figure it was drawn on. */
const chapters = new Map<
  string,
  { state: chapter.ChapterState | null; zoom: Zoom | null; heldRecord: number | null }
>(SPECS.map((spec) => [spec.id, { state: null, zoom: null, heldRecord: null }]));

async function loadJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

function slot(id: string) {
  const found = chapters.get(id);
  if (!found) throw new Error(`unknown chapter ${id}`);
  return found;
}

function refreshChrome(): void {
  syncControls(view);
  renderNotes(summary, view);
  renderStatus(summary, view, rejected);
}

/** A chapter's own view: the shared selection, with that chapter's brush applied. */
function chapterView(id: string): View {
  return { ...view, zoom: slot(id).zoom };
}

async function rebuild(spec: (typeof SPECS)[number]): Promise<void> {
  const entry = slot(spec.id);
  const container = byId(`${spec.id}-strip`).closest(".figure");
  container?.setAttribute("aria-busy", "true");
  try {
    const file = assertPanelSchema(await chapter.loadPanels(view.selection));
    entry.state = chapter.buildState(
      spec,
      summary,
      records,
      chapterView(spec.id),
      file,
      entry.heldRecord,
    );
    chapter.render(entry.state);
    paintInspection(spec.id);
  } catch (error) {
    byId(`${spec.id}-note`).textContent =
      `Could not load this figure: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    container?.removeAttribute("aria-busy");
  }
}

/** Redraw without refetching — for a filter, colour or brush change. */
function redraw(id: string): void {
  const entry = slot(id);
  if (!entry.state) return;
  chapter.applyView(entry.state, chapterView(id));
  chapter.render(entry.state);
  paintInspection(id);
}

function paintInspection(id: string): void {
  const entry = slot(id);
  if (!entry.state) return;
  const spec = entry.state.spec;
  const set = chapter.currentSet(entry.state);
  renderReadout(spec, records, set, entry.state.held ?? entry.state.inspected, !!entry.state.held);
  paintPinned();
  wireRenderedControls(id);
}

/** One inspector for the page, assembled from every chapter that holds the record.
 *
 *  Also the only place `type_concordance` and the panel-scoped coverage can be read:
 *  the colour control can paint by both, but neither is a recorded field, so without
 *  this the reader could see a colour they could not look up. */
function paintPinned(): void {
  const row = [...chapters.values()].find((entry) => entry.heldRecord !== null)?.heldRecord ?? null;
  if (row === null) {
    renderPinned(records, null, [], []);
    return;
  }

  const panels: PinnedPanel[] = [];
  for (const spec of SPECS) {
    const state = slot(spec.id).state;
    if (!state) continue;
    const set = chapter.currentSet(state);
    const mark = state.held ?? set.marks.find((m) => m.record === row);
    if (!mark) continue;
    panels.push({
      figure: spec.id === "divergence" ? "Divergence" : "Distance",
      region: summary.regions.find((r) => r.id === state.region)?.label ?? state.region,
      rows: spec.measured(set, mark),
    });
  }

  const derived: DerivedField[] = [];
  const anyState = slot(SPECS[0]!.id).state;
  if (anyState) {
    const concordance = chapter.concordanceValue(summary, records, {
      ...view,
      trait: "type_concordance",
    });
    const value = concordance?.(row);
    if (value) {
      derived.push({
        label: summary.traits.find((t) => t.id === "type_concordance")?.label ?? "Type concordance",
        value,
        why: "Curated virus_type judged against the alignment this record was placed in, so it depends on the serotype selected.",
      });
    }
  }

  renderPinned(records, row, panels, derived);
}

/** Buttons that live inside re-rendered markup need rebinding, not one listener at
 *  mount. */
function wireRenderedControls(id: string): void {
  byId("record-detail")
    .querySelector<HTMLButtonElement>("[data-unpin]")
    ?.addEventListener("click", () => setHeld(id, null));
  byId(`${id}-note`)
    .querySelector<HTMLButtonElement>("[data-reset-zoom]")
    ?.addEventListener("click", () => {
      slot(id).zoom = null;
      redraw(id);
    });
}

function commit(next: View, { reload }: { reload: boolean }): void {
  view = next;
  rejected = [];
  writeHash();
  refreshChrome();
  for (const spec of SPECS) {
    if (reload || !slot(spec.id).state) void rebuild(spec);
    else redraw(spec.id);
  }
}

function handleEdit(): void {
  const next = readControls(view);
  if (sameView({ ...next, zoom: view.zoom }, view)) return;
  if (next.selection !== view.selection) {
    next.trait = traitAfterSelectionChange(summary, view.selection, next.selection, view.trait);
  }
  // A new selection, region or scale means new marks — the scale selects which
  // embedding the distance chapter shows, not just how its axis is drawn. A filter or
  // colour change is only a redraw, and the colour assignment is deliberately not
  // rebuilt. Rebuilding is cheap after the first load: the panel file is cached, so
  // this re-decodes rather than refetches.
  const reload =
    next.selection !== view.selection ||
    next.region !== view.region ||
    next.scale !== view.scale;
  if (next.selection !== view.selection) {
    for (const entry of chapters.values()) {
      entry.zoom = null;
      entry.heldRecord = null;
    }
  }
  commit({ ...next, zoom: null }, { reload });
}

function writeHash(): void {
  const encoded = encode({ ...view, zoom: null }, summary);
  const target = encoded ? `#${encoded}` : "#top";
  if (location.hash === target) return;
  writingHash = true;
  history.replaceState(null, "", target);
  writingHash = false;
}

function handleHashChange(): void {
  if (writingHash) return;
  const decoded = decode(location.hash, summary);
  view = decoded.view;
  rejected = decoded.rejected;
  refreshChrome();
  for (const spec of SPECS) void rebuild(spec);
}

function setInspected(id: string, mark: Mark | null): void {
  const entry = slot(id);
  if (!entry.state || entry.state.inspected === mark) return;
  entry.state.inspected = mark;
  chapter.renderHighlight(entry.state);
  const set = chapter.currentSet(entry.state);
  renderReadout(entry.state.spec, records, set, mark ?? entry.state.held, !!entry.state.held);
}

function setHeld(id: string, mark: Mark | null): void {
  const entry = slot(id);
  if (!entry.state) return;
  entry.state.held = mark;
  entry.heldRecord = mark ? mark.record : null;
  // A pinned record is a cross-chapter idea: pinning here highlights the same record
  // in the other figure, which is what makes the two views one instrument.
  for (const [other, otherEntry] of chapters) {
    if (other === id || !otherEntry.state) continue;
    otherEntry.heldRecord = entry.heldRecord;
    otherEntry.state.held =
      entry.heldRecord === null
        ? null
        : (otherEntry.state.visibleMarks.find((m) => m.record === entry.heldRecord) ?? null);
    chapter.renderHighlight(otherEntry.state);
    paintInspection(other);
  }
  view.pinned = mark ? records.accession(mark.record) : null;
  writeHash();
  chapter.renderHighlight(entry.state);
  paintInspection(id);
}

function wireChapter(spec: (typeof SPECS)[number]): void {
  const canvas = byId<HTMLCanvasElement>(`${spec.id}-canvas`);
  const id = spec.id;
  /** A press becomes a zoom if the pointer travels past this many plot units, and a
   *  pin if it does not — one gesture serves both without a modifier. */
  const DRAG_THRESHOLD = 5;
  let start: [number, number] | null = null;
  let moved = false;

  canvas.addEventListener("pointerdown", (event) => {
    const state = slot(id).state;
    if (event.button !== 0 || !state) return;
    start = chapter.positionAt(state, event.clientX, event.clientY);
    moved = false;
    if (start) canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    const state = slot(id).state;
    if (!state) return;
    if (start) {
      const at = chapter.positionAt(state, event.clientX, event.clientY);
      if (!at) return;
      if (Math.abs(at[0] - start[0]) > DRAG_THRESHOLD || Math.abs(at[1] - start[1]) > DRAG_THRESHOLD) {
        moved = true;
      }
      if (moved) {
        state.brush = { x0: start[0], y0: start[1], x1: at[0], y1: at[1] };
        setInspected(id, null);
        chapter.renderHighlight(state);
      }
      return;
    }
    setInspected(id, chapter.markAt(state, event.clientX, event.clientY));
  });

  canvas.addEventListener("pointerup", (event) => {
    const state = slot(id).state;
    if (!state || !start) return;
    const at = chapter.positionAt(state, event.clientX, event.clientY);
    const from = start;
    const dragged = moved;
    start = null;
    moved = false;
    state.brush = null;

    if (dragged && at) {
      const zoom = chapter.boxToZoom(state, { x0: from[0], y0: from[1], x1: at[0], y1: at[1] });
      // A box holding nothing is a slip, not an instruction; leave the view alone.
      if (zoom) {
        slot(id).zoom = zoom;
        redraw(id);
      } else {
        chapter.renderHighlight(state);
      }
      return;
    }
    const mark = chapter.markAt(state, event.clientX, event.clientY);
    if (mark) setHeld(id, mark);
  });

  const cancel = () => {
    const state = slot(id).state;
    start = null;
    moved = false;
    if (state) {
      state.brush = null;
      chapter.renderHighlight(state);
    }
  };
  canvas.addEventListener("pointercancel", cancel);
  canvas.addEventListener("pointerleave", () => {
    if (!start) setInspected(id, null);
  });

  canvas.addEventListener("dblclick", () => {
    if (slot(id).zoom) {
      slot(id).zoom = null;
      redraw(id);
    }
  });

  // Keyboard parity: every value reachable by hover must be reachable without a
  // pointer, so arrows walk the cloud and Enter pins.
  canvas.addEventListener("keydown", (event) => {
    const state = slot(id).state;
    if (!state) return;
    const marks = chapter.ordered(state);
    if (!marks.length) return;
    const at = state.inspected ? marks.indexOf(state.inspected) : -1;
    let next = at;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowUp":
        next = at < 0 ? 0 : Math.min(marks.length - 1, at + 1);
        break;
      case "ArrowLeft":
      case "ArrowDown":
        next = at < 0 ? marks.length - 1 : Math.max(0, at - 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = marks.length - 1;
        break;
      case "Enter":
        if (state.inspected) setHeld(id, state.inspected);
        event.preventDefault();
        return;
      case "Escape":
        if (slot(id).zoom) {
          slot(id).zoom = null;
          redraw(id);
        }
        setInspected(id, null);
        setHeld(id, null);
        return;
      default:
        return;
    }
    event.preventDefault();
    setInspected(id, marks[next] ?? null);
  });

  byId(`${id}-strip`).addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(".thumb");
    if (!button?.dataset.region) return;
    // A region change invalidates every chapter's brush: the same rectangle means
    // something different once the axes have moved.
    for (const entry of chapters.values()) entry.zoom = null;
    commit({ ...view, region: button.dataset.region, zoom: null }, { reload: false });
  });
}

async function main(): Promise<void> {
  const [loadedSummary, manifest, recordTable] = await Promise.all([
    loadJson<Summary>("data/summary.json"),
    loadJson<Manifest>("data/manifest.json"),
    loadJson<RecordTable>("data/records.json"),
  ]);
  summary = assertSchema(loadedSummary);
  records = new Records(recordTable);

  const decoded = decode(location.hash, summary);
  view = decoded.view;
  rejected = decoded.rejected;

  renderRawDate(summary);
  renderReleaseBand(summary);
  renderFacts(summary);
  renderPopulationTable(summary);
  renderDataQuality(summary);
  renderIntegrityNotes(summary);
  renderBuildLine(summary, manifest.build_identity);

  renderControls(summary, view);
  onControlEdit(handleEdit);
  for (const spec of SPECS) wireChapter(spec);
  refreshChrome();
  await Promise.all(SPECS.map((spec) => rebuild(spec)));

  // A pinned accession restored from the URL has to wait for the panels to exist.
  if (view.pinned) {
    const first = slot(DIVERGENCE.id).state;
    const target = first?.visibleMarks.find(
      (mark) => records.accession(mark.record) === view.pinned,
    );
    if (target) setHeld(DIVERGENCE.id, target);
  }

  byId("reset-view").addEventListener("click", () => {
    for (const entry of chapters.values()) {
      entry.zoom = null;
      entry.heldRecord = null;
    }
    commit(defaultView(summary), { reload: true });
  });
  window.addEventListener("hashchange", handleHashChange);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  const band = byId("release-band");
  band.innerHTML = `<strong>Could not load the release summary.</strong><span>${message}</span>`;
  band.classList.add("is-stale");
  console.error(error);
});
