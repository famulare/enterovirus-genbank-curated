/** The shared record table, decoded.
 *
 *  Columns arrive dictionary-encoded where that saves space and raw where it does
 *  not, so this module hides the difference behind one accessor. Records are
 *  addressed by their index in the canonical file, which is what the panel files
 *  reference — no accession strings in the figure payloads.
 */

export type Column =
  | { kind: "raw"; values: string[] }
  | { kind: "dictionary"; table: string[]; index: number[] }
  | { kind: "numeric"; values: (number | null)[] };

export interface RecordTable {
  schema: number;
  n: number;
  accession: string[];
  manual_decision: number[];
  columns: Record<string, Column>;
  labels: Record<string, string>;
}

export const RECORDS_SCHEMA = 1;

export class Records {
  private readonly table: RecordTable;
  private readonly decided: Set<number>;

  constructor(table: RecordTable) {
    if (table.schema !== RECORDS_SCHEMA) {
      throw new Error(
        `records.json is schema ${table.schema}, this app reads ${RECORDS_SCHEMA}. ` +
          "Rebuild with: uv run site/pipeline/cli.py build",
      );
    }
    this.table = table;
    this.decided = new Set(table.manual_decision);
  }

  get size(): number {
    return this.table.n;
  }

  get fields(): string[] {
    return Object.keys(this.table.columns);
  }

  label(field: string): string {
    return this.table.labels[field] ?? field;
  }

  accession(row: number): string {
    return this.table.accession[row] ?? "";
  }

  hasManualDecision(row: number): boolean {
    return this.decided.has(row);
  }

  /** Text value, or "" when absent. Accession is served from its own array. */
  text(field: string, row: number): string {
    if (field === "accession") return this.accession(row);
    const column = this.table.columns[field];
    if (!column) return "";
    if (column.kind === "raw") return column.values[row] ?? "";
    if (column.kind === "dictionary") {
      const index = column.index[row] ?? 0;
      return index === 0 ? "" : (column.table[index - 1] ?? "");
    }
    const value = column.values[row];
    return value === null || value === undefined ? "" : String(value);
  }

  /** Numeric value, or null when the field is not numeric or has no value. */
  number(field: string, row: number): number | null {
    const column = this.table.columns[field];
    if (!column) return null;
    if (column.kind === "numeric") return column.values[row] ?? null;
    const raw = this.text(field, row);
    if (!raw) return null;
    const parsed = Number(raw);
    return Number.isFinite(parsed) ? parsed : null;
  }

  /** Distinct values with counts, over the given rows. Used to rank categories. */
  tally(field: string, rows: Iterable<number>): Map<string, number> {
    const counts = new Map<string, number>();
    for (const row of rows) {
      const value = this.text(field, row);
      counts.set(value, (counts.get(value) ?? 0) + 1);
    }
    return counts;
  }

  /** Every canonical field of one record, in declared order, for the detail view. */
  detail(row: number): { field: string; label: string; value: string }[] {
    const out = [{ field: "accession", label: this.label("accession"), value: this.accession(row) }];
    for (const field of this.fields) {
      out.push({ field, label: this.label(field), value: this.text(field, row) });
    }
    return out;
  }
}
