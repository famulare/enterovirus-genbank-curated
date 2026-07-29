/** Two tiers of record inspection, shared by both figure chapters.
 *
 *  Hover (or arrow-key focus) shows a compact readout: enough to know what a mark is
 *  without a wall of text. Click pins the record and opens every canonical field below
 *  the figure. Twenty-four fields in a hover tooltip would be unreadable, and a
 *  hover-only value is unreachable by keyboard, so the exact numbers live in the
 *  persistent view and the tooltip is a summary.
 */

import type { Mark, MarkSet } from "../model/mark.js";
import type { ChapterSpec } from "./chapter.js";
import type { Records } from "../model/records.js";
import { byId, esc } from "./dom.js";

const GENBANK = "https://www.ncbi.nlm.nih.gov/nuccore/";

export function renderReadout(
  spec: ChapterSpec,
  records: Records,
  set: MarkSet,
  mark: Mark | null,
  held: boolean,
): void {
  const target = byId(`${spec.id}-readout`);
  if (!mark) {
    target.classList.remove("is-active");
    target.innerHTML =
      `<span class="readout-hint">Hover or arrow-key a mark to read it; click to pin every
       field. Drag a box to zoom.</span>`;
    return;
  }
  target.classList.add("is-active");

  const type = records.text("virus_type", mark.record) || "untyped";
  const classification = records.text("poliovirus_classification", mark.record);
  const country = records.text("country", mark.record);
  const date = records.text("collection_date", mark.record);

  const lines = [
    `<span class="readout-key">${esc(records.accession(mark.record))}</span>`,
    `<span>${esc(type)}${classification ? ` · ${esc(classification)}` : ""}</span>`,
    `<span>${esc([country, date].filter(Boolean).join(" · ") || "no place or date recorded")}</span>`,
    ...spec.readout(records, set, mark).map((line) => `<span>${line}</span>`),
  ];
  if (!held) lines.push('<span class="readout-hint">Click to pin</span>');
  target.innerHTML = lines.join("");
}

export function renderPinned(
  spec: ChapterSpec,
  records: Records,
  set: MarkSet,
  mark: Mark | null,
): void {
  const target = byId(`${spec.id}-detail`);
  if (!mark) {
    target.innerHTML = "";
    target.removeAttribute("data-open");
    return;
  }
  target.dataset.open = "true";

  const accession = records.accession(mark.record);
  const measured = spec.measured(set, mark);
  const rows = records
    .detail(mark.record)
    .filter((entry) => entry.value !== "")
    .map((entry) => `<tr><th scope="row">${esc(entry.label)}</th><td>${esc(entry.value)}</td></tr>`)
    .join("");

  target.innerHTML = `
    <div class="detail-head">
      <div>
        <p class="eyebrow">Pinned record</p>
        <h3>${esc(accession)}</h3>
      </div>
      <button type="button" class="text-button" data-unpin>Clear</button>
    </div>
    <div class="detail-grid">
      <div>
        <p class="detail-subhead">Measured in this panel</p>
        <dl class="detail-measured">
          ${measured
            .map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`)
            .join("")}
        </dl>
        <p class="detail-links">
          <a href="${GENBANK}${encodeURIComponent(accession)}" rel="noopener">This record on
            GenBank</a>
          ${
            records.hasManualDecision(mark.record)
              ? ' · <span class="prov-tag" data-kind="derived">Human curation decision recorded</span>'
              : ' · <span class="prov-tag" data-kind="assumption">No human decision recorded</span>'
          }
        </p>
      </div>
      <div class="table-wrap record-table detail-fields">
        <p class="detail-subhead">Every recorded field</p>
        <table><tbody>${rows}</tbody></table>
      </div>
    </div>
  `;
}
