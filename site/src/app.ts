/** Mount. Loads the built artifacts, renders the chrome and the divergence figure,
 *  and keeps the URL hash and the control DOM in step with each other. */

import { assertSchema, type Summary } from "./model/types.js";
import { decode, defaultView, encode, sameView, type View } from "./model/view.js";
import { Records, type RecordTable } from "./model/records.js";
import { decodeRegion, type Panel, type Point } from "./model/panel.js";
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
  renderPendingCounts,
  renderPopulationTable,
  renderRawDate,
  renderReleaseBand,
} from "./ui/report.js";
import * as figure from "./ui/figure.js";
import { renderPinned, renderReadout } from "./ui/detail.js";
import { byId } from "./ui/dom.js";

interface Manifest {
  build_identity: string;
}

let summary: Summary;
let records: Records;
let view: View;
let rejected: string[] = [];
let state: figure.FigureState | null = null;
let writingHash = false;

async function loadJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  return (await response.json()) as T;
}

function currentPanel(): Panel {
  return (
    state?.panels.get(view.region) ??
    decodeRegion(state!.file, state!.regions[0]!)
  );
}

/** Everything that depends on the view but not on the panel payload. */
function refreshChrome(): void {
  syncControls(view);
  renderNotes(summary, view);
  renderStatus(summary, view, rejected);
  renderPendingCounts(summary, view);
}

async function refreshFigure(): Promise<void> {
  const figures = byId("divergence-strip").closest(".figure");
  figures?.setAttribute("aria-busy", "true");
  try {
    const file = await figure.loadPanels(view.selection);
    const previousHeld = state?.held ?? null;
    state = figure.buildState(summary, records, view, file);
    // A pinned record survives a region or colour change if it is still on screen.
    if (previousHeld) {
      state.held =
        currentPanel().points.find((point) => point.record === previousHeld.record) ?? null;
    }
    figure.render(state);
    renderReadout(records, currentPanel(), state.held, true);
    renderPinned(records, currentPanel(), state.held);
    wirePinnedControls();
  } catch (error) {
    byId("divergence-note").textContent =
      `Could not load the figure data: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    figures?.removeAttribute("aria-busy");
  }
}

function commit(next: View): void {
  const needsReload =
    next.selection !== view.selection || next.region !== view.region || next.trait !== view.trait;
  view = next;
  rejected = [];
  writeHash();
  refreshChrome();
  if (needsReload || !state) {
    void refreshFigure();
    return;
  }
  state.view = view;
  figure.render(state);
  wirePinnedControls();
}

function handleEdit(): void {
  const next = readControls(view);
  if (sameView(next, view)) return;
  if (next.selection !== view.selection) {
    next.trait = decode(`sel=${next.selection}`, summary).view.trait;
  }
  // Filter changes need a redraw but not a reload; the scale is deliberately not
  // rebuilt, so surviving categories keep their colors.
  const redrawOnly =
    next.selection === view.selection &&
    next.region === view.region &&
    next.trait === view.trait;
  view = next;
  rejected = [];
  writeHash();
  refreshChrome();
  if (redrawOnly && state) {
    state.view = view;
    figure.render(state);
    wirePinnedControls();
  } else {
    void refreshFigure();
  }
}

function writeHash(): void {
  const encoded = encode(view, summary);
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
  void refreshFigure();
}

function setInspected(point: Point | null): void {
  if (!state || state.inspected === point) return;
  state.inspected = point;
  figure.renderHighlight(state);
  renderReadout(records, currentPanel(), point ?? state.held, state.held !== null);
}

function setHeld(point: Point | null): void {
  if (!state) return;
  state.held = point;
  view.pinned = point ? records.accession(point.record) : null;
  writeHash();
  figure.renderHighlight(state);
  renderPinned(records, currentPanel(), point);
  renderReadout(records, currentPanel(), point ?? state.inspected, point !== null);
  wirePinnedControls();
}

function wirePinnedControls(): void {
  document.getElementById("unpin-record")?.addEventListener("click", () => setHeld(null));
  // Rendered into the figure note, so it is replaced on every render and needs
  // rebinding rather than one listener at mount.
  document
    .getElementById("reset-zoom")
    ?.addEventListener("click", () => commit({ ...view, zoom: null }));
}

/** Brush state. A press becomes a zoom if the pointer travels past this many plot
 *  units, and a pin if it does not — so one gesture serves both without a modifier. */
const DRAG_THRESHOLD = 5;
let brushStart: [number, number] | null = null;
let brushMoved = false;

function wireFigure(): void {
  const canvas = byId<HTMLCanvasElement>("divergence-canvas");

  canvas.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    brushStart = figure.positionAt(event.clientX, event.clientY);
    brushMoved = false;
    if (brushStart) canvas.setPointerCapture(event.pointerId);
  });

  canvas.addEventListener("pointermove", (event) => {
    if (!state) return;
    if (brushStart) {
      const at = figure.positionAt(event.clientX, event.clientY);
      if (!at) return;
      if (
        Math.abs(at[0] - brushStart[0]) > DRAG_THRESHOLD ||
        Math.abs(at[1] - brushStart[1]) > DRAG_THRESHOLD
      ) {
        brushMoved = true;
      }
      if (brushMoved) {
        figure.setBrush({ x0: brushStart[0], y0: brushStart[1], x1: at[0], y1: at[1] });
        // Suppress the readout mid-drag: the reader is choosing a range, not a record.
        setInspected(null);
        figure.renderHighlight(state);
      }
      return;
    }
    setInspected(figure.pointAt(state, event.clientX, event.clientY));
  });

  canvas.addEventListener("pointerup", (event) => {
    if (!state || !brushStart) return;
    const at = figure.positionAt(event.clientX, event.clientY);
    const start = brushStart;
    const moved = brushMoved;
    brushStart = null;
    brushMoved = false;
    figure.setBrush(null);

    if (moved && at) {
      const zoom = figure.boxToZoom(state, { x0: start[0], y0: start[1], x1: at[0], y1: at[1] });
      // A box holding nothing is a slip, not an instruction; leave the view alone.
      if (zoom) {
        commit({ ...view, zoom });
        return;
      }
      figure.renderHighlight(state);
      return;
    }
    const point = figure.pointAt(state, event.clientX, event.clientY);
    if (point) setHeld(point);
  });

  canvas.addEventListener("pointercancel", () => {
    brushStart = null;
    brushMoved = false;
    figure.setBrush(null);
    if (state) figure.renderHighlight(state);
  });

  canvas.addEventListener("pointerleave", () => {
    if (!brushStart) setInspected(null);
  });

  // Double-click is the fast way back out, alongside the note's button.
  canvas.addEventListener("dblclick", () => {
    if (view.zoom) commit({ ...view, zoom: null });
  });

  // Keyboard parity: the same values reachable by hover must be reachable without a
  // pointer, so arrows walk the cloud in x order and Enter pins.
  canvas.addEventListener("keydown", (event) => {
    if (!state) return;
    const points = figure.ordered(state);
    if (!points.length) return;
    const at = state.inspected ? points.indexOf(state.inspected) : -1;
    let next = at;
    switch (event.key) {
      case "ArrowRight":
      case "ArrowUp":
        next = at < 0 ? 0 : Math.min(points.length - 1, at + 1);
        break;
      case "ArrowLeft":
      case "ArrowDown":
        next = at < 0 ? points.length - 1 : Math.max(0, at - 1);
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = points.length - 1;
        break;
      case "Enter":
        if (state.inspected) setHeld(state.inspected);
        event.preventDefault();
        return;
      case "Escape":
        if (view.zoom) commit({ ...view, zoom: null });
        setInspected(null);
        setHeld(null);
        return;
      default:
        return;
    }
    event.preventDefault();
    setInspected(points[next] ?? null);
  });

  byId("divergence-strip").addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>(".thumb");
    if (!button?.dataset.region) return;
    commit({ ...view, region: button.dataset.region });
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
  wireFigure();
  refreshChrome();
  await refreshFigure();

  // A pinned accession restored from the URL has to wait for the panel to exist.
  if (view.pinned && state) {
    const target = currentPanel().points.find(
      (point) => records.accession(point.record) === view.pinned,
    );
    if (target) setHeld(target);
  }

  byId("reset-view").addEventListener("click", () => commit(defaultView(summary)));
  window.addEventListener("hashchange", handleHashChange);
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : String(error);
  const band = byId("release-band");
  band.innerHTML = `<strong>Could not load the release summary.</strong><span>${message}</span>`;
  band.classList.add("is-stale");
  console.error(error);
});
