/** Minimal DOM helpers. No framework, no virtual DOM, no store. */

/** Throws rather than returning null, so template-versus-script drift is a loud
 *  failure at mount instead of a silent no-op later.
 *
 *  Constrained to Element rather than HTMLElement so the SVG layers can be
 *  requested by their own type; the default stays HTMLElement so unparameterized
 *  callers keep `dataset` and friends. */
export function byId<T extends Element = HTMLElement>(id: string): T {
  const found = document.getElementById(id);
  if (!found) throw new Error(`Missing UI element #${id}`);
  return found as unknown as T;
}

const ESCAPES: Record<string, string> = {
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;",
};

/** Every value interpolated into a template string goes through this. Field
 *  values come from GenBank submitters, so they are untrusted text. */
export function esc(value: unknown): string {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ESCAPES[char]!);
}

export function num(value: number): string {
  return value.toLocaleString("en-US");
}

export function option(value: string, label: string, selected: boolean): string {
  return `<option value="${esc(value)}"${selected ? " selected" : ""}>${esc(label)}</option>`;
}
