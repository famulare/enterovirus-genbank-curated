/** Two tiers of record inspection.
 *
 *  Hover (or arrow-key focus) shows a compact readout: enough to know what a mark is
 *  without a wall of text. Click pins the record and opens every canonical field
 *  below the figure. Twenty-four fields in a hover tooltip would be unreadable, and
 *  a hover-only value is unreachable by keyboard, so the exact numbers live in the
 *  persistent view and the tooltip is a summary.
 */

import type { Panel, Point } from "../model/panel.js";
import type { Records } from "../model/records.js";
import { byId, esc, num } from "./dom.js";

const GENBANK = "https://www.ncbi.nlm.nih.gov/nuccore/";

function rate(numerator: number, denominator: number): string {
  return denominator === 0 ? "—" : (numerator / denominator).toFixed(4);
}

export function renderReadout(
  records: Records,
  panel: Panel,
  point: Point | null,
  held: boolean,
): void {
  const target = byId("divergence-readout");
  if (!point) {
    target.classList.remove("is-active");
    target.innerHTML =
      `<span class="readout-hint">Hover or arrow-key a mark to read it; click to pin every field.</span>`;
    return;
  }
  target.classList.add("is-active");
  const reference = panel.references[point.reference]?.label ?? "reference";
  const type = records.text("virus_type", point.record) || "untyped";
  const classification = records.text("poliovirus_classification", point.record);
  const country = records.text("country", point.record);
  const date = records.text("collection_date", point.record);

  target.innerHTML = `
    <span class="readout-key">${esc(records.accession(point.record))}</span>
    <span>${esc(type)}${classification ? ` · ${esc(classification)}` : ""}</span>
    <span>${esc([country, date].filter(Boolean).join(" · ") || "no place or date recorded")}</span>
    <span><b>${point.synonymous}</b> syn, <b>${point.nonsynonymous}</b> non-syn over
      <b>${num(point.assessable)}</b> codons → ${rate(point.synonymous, point.assessable)},
      ${rate(point.nonsynonymous, point.assessable)}</span>
    <span>vs ${esc(reference)}${
      point.indelCodons ? ` · ${point.indelCodons} indel codon(s)` : ""
    }${point.frameshift ? " · frameshifting indel" : ""}</span>
    ${held ? "" : '<span class="readout-hint">Click to pin</span>'}
  `;
}

export function renderPinned(
  records: Records,
  panel: Panel,
  point: Point | null,
): void {
  const target = byId("divergence-detail");
  if (!point) {
    target.innerHTML = "";
    target.removeAttribute("data-open");
    return;
  }
  target.dataset.open = "true";

  const accession = records.accession(point.record);
  const reference = panel.references[point.reference];
  const measured: [string, string][] = [
    ["Codons compared", num(point.assessable)],
    ["— both unambiguous", num(point.comparable)],
    ["— touched by an indel", num(point.indelCodons)],
    [
      "Synonymous differences",
      `${num(point.synonymous)} (${rate(point.synonymous, point.assessable)} per codon)`,
    ],
    [
      "Non-synonymous differences",
      `${num(point.nonsynonymous)} (${rate(point.nonsynonymous, point.assessable)} per codon)`,
    ],
    ["Indel events", point.indelEvents ? num(point.indelEvents) : "none"],
    ["Reading frame", point.frameshift ? "frameshifting indel present" : "intact"],
    ["Measured against", reference ? `${reference.label} (${reference.kind})` : "—"],
  ];

  const rows = records
    .detail(point.record)
    .filter((entry) => entry.value !== "")
    .map(
      (entry) =>
        `<tr><th scope="row">${esc(entry.label)}</th><td>${esc(entry.value)}</td></tr>`,
    )
    .join("");

  target.innerHTML = `
    <div class="detail-head">
      <div>
        <p class="eyebrow">Pinned record</p>
        <h3>${esc(accession)}</h3>
      </div>
      <button type="button" class="text-button" id="unpin-record">Clear</button>
    </div>
    <div class="detail-grid">
      <div>
        <p class="detail-subhead">Measured in this panel</p>
        <dl class="detail-measured">
          ${measured.map(([key, value]) => `<div><dt>${esc(key)}</dt><dd>${esc(value)}</dd></div>`).join("")}
        </dl>
        <p class="detail-links">
          <a href="${GENBANK}${encodeURIComponent(accession)}" rel="noopener">This record on GenBank</a>
          ${
            records.hasManualDecision(point.record)
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
