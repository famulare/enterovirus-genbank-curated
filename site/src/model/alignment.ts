/** The alignment behind the other five figures, decoded.
 *
 *  DOM-free and unit-tested. This module owns two things: the container format the
 *  Python side writes, and the two cell vocabularies the raster draws.
 *
 *  The second of those is a deliberate duplication. `pipeline/divergence.py` already
 *  computes every one of these classifications and throws them away, keeping only the
 *  row totals that figure 1 plots. Rather than ship the states — which would cost bytes
 *  and forbid the letter-level zoom — the states are recomputed here from the bases.
 *  The risk that this drifts from the Python is closed by `test/alignment.test.ts`,
 *  which recomputes the totals through this module and asserts they equal
 *  `panels/*.json` exactly. That checks two implementations against each other, which
 *  is the failure actually worth guarding.
 */

/** Normalized codes, mirroring `pipeline/frame.py`. The distinction between GAP and
 *  AMBIGUOUS is load-bearing: folding an `N` into a gap would draw a one-base deletion
 *  on a sequence that has none. */
export const GAP = 0;
export const AMBIGUOUS = 5;

/** What a record carries at one column. */
export const COVERAGE = {
  /** Outside the record's span — it has no material here, which is missing data. */
  ABSENT: 0,
  /** Inside the span but empty: a deletion relative to the alignment. */
  GAP: 1,
  /** Material present but unreadable — `N` and the IUPAC set. */
  AMBIGUOUS: 2,
  BASE: 3,
} as const;

/** What one codon contributed to figure 1. The row-sums of this vocabulary are exactly
 *  that figure's two axes, which `test/alignment.test.ts` asserts against the panels. */
export const DIVERGENCE = {
  /** Not in the assessable denominator at all. */
  UNCOMPARABLE: 0,
  IDENTICAL: 1,
  SYNONYMOUS: 2,
  NONSYNONYMOUS: 3,
  DELETION: 4,
  INSERTION: 5,
  /** This record has no comparable reference, so figure 1 reports it unmeasurable. */
  NO_REFERENCE: 6,
} as const;

/** Normalized code -> its offset in the TCAG ordering the standard table is written in.
 *  GAP and AMBIGUOUS both map to 0 so an unreadable codon still yields an in-range
 *  lookup; callers mask those out by comparability and never trust the result. */
const TCAG = new Uint8Array([0, 2, 1, 3, 0, 0]);
const AMINO =
  "FFLLSSSSYY**CC*W" +
  "LLLLPPPPHHQQRRRR" +
  "IIIMTTTTNNKKSSRR" +
  "VVVVAAAADDEEGGGG";

function isBase(code: number): boolean {
  return code >= 1 && code <= 4;
}

export interface AlignmentSection {
  name: string;
  type: "i32" | "u8";
  bytes: number;
}

export interface AlignmentHeader {
  schema: number;
  selection: string;
  region: string;
  coding: boolean;
  width: number;
  n_rows: number;
  min_nt: number;
  references?: { kind: string; label: string }[];
  sections: AlignmentSection[];
}

export const ALIGNMENT_SCHEMA = 1;

/** The per-region coverage profiles that draw the thumbnail strip.
 *
 *  Shipped as its own small file per selection and loaded eagerly, because the strip
 *  has to show every region at once while only the focus region's cells are worth
 *  fetching. A miniature raster per thumbnail would mean holding all six regions
 *  resident and repainting them on every filter, colour and brush change. */
export interface ProfileFile {
  schema: number;
  selection: string;
  n_rows: number;
  regions: Record<string, { width: number; covered: number[] }>;
}

export function assertProfileSchema(file: ProfileFile): ProfileFile {
  if (file.schema !== ALIGNMENT_SCHEMA) {
    throw new Error(
      `alignment profile is schema ${file.schema}, this app reads ${ALIGNMENT_SCHEMA}. ` +
        "Rebuild with: uv run site/pipeline/cli.py build",
    );
  }
  return file;
}

/** Rows of one region's alignment, addressed by raster row.
 *
 *  Cells stay nibble-packed for the life of the block. Unpacking `all`/P1 would cost
 *  40 MB against 15 for the packed form, and nothing ever needs more than one row at a
 *  time, so rows are expanded into a caller-supplied scratch buffer instead.
 */
export class AlignmentBlock {
  readonly header: AlignmentHeader;
  readonly record: Int32Array;
  readonly first: Int32Array;
  readonly last: Int32Array;
  readonly reference: Int32Array | null;
  readonly cells: Uint8Array;
  readonly referenceCells: Uint8Array | null;
  /** Byte offset of each row's span within `cells`, plus a terminator.
   *
   *  Derived rather than shipped: a row occupies ceil(span / 2) bytes, so an offset
   *  table would be a second copy of a derivable fact and a second thing that can
   *  disagree with the cells it indexes. */
  readonly offsets: Float64Array;
  private readonly rowOf: Map<number, number>;
  private readonly scratch: Uint8Array;
  /** Expanded reference rows, by slot. There are a handful of Sabin rows and at most a
   *  few hundred type consensuses, but `columnTrack` asks for one per visible row — so
   *  without this a single pass over `all`/P1 would allocate and discard 24,305 buffers
   *  of 3,342 bytes apiece. */
  private readonly referenceCache = new Map<number, Uint8Array>();

  constructor(header: AlignmentHeader, sections: Map<string, Int32Array | Uint8Array>) {
    if (header.schema !== ALIGNMENT_SCHEMA) {
      throw new Error(
        `alignment payload is schema ${header.schema}, this app reads ${ALIGNMENT_SCHEMA}. ` +
          "Rebuild with: uv run site/pipeline/cli.py build",
      );
    }
    this.header = header;
    this.record = sections.get("record") as Int32Array;
    this.first = sections.get("first") as Int32Array;
    this.last = sections.get("last") as Int32Array;
    this.reference = (sections.get("reference") as Int32Array) ?? null;
    this.cells = sections.get("cells") as Uint8Array;
    this.referenceCells = (sections.get("reference_cells") as Uint8Array) ?? null;

    this.offsets = new Float64Array(header.n_rows + 1);
    for (let row = 0; row < header.n_rows; row += 1) {
      const span = this.last[row]! >= this.first[row]! ? this.last[row]! - this.first[row]! + 1 : 0;
      this.offsets[row + 1] = this.offsets[row]! + ((span + 1) >> 1);
    }
    if (this.offsets[header.n_rows] !== this.cells.length) {
      throw new Error(
        `${header.selection}/${header.region}: spans imply ${this.offsets[header.n_rows]} cell ` +
          `bytes but ${this.cells.length} shipped`,
      );
    }

    this.rowOf = new Map();
    for (let row = 0; row < this.record.length; row += 1) this.rowOf.set(this.record[row]!, row);
    this.scratch = new Uint8Array(header.width);
  }

  get width(): number {
    return this.header.width;
  }

  get rows(): number {
    return this.header.n_rows;
  }

  /** Raster row holding a record, or -1. The join is on record index and never on
   *  position: this block carries every row of the population, while a panel keeps only
   *  those clearing the coverage floor with a reference resolved. */
  rowForRecord(record: number): number {
    return this.rowOf.get(record) ?? -1;
  }

  /** One row expanded to full region width, gaps included. The returned buffer is
   *  reused on the next call. */
  row(index: number): Uint8Array {
    const out = this.scratch;
    out.fill(GAP);
    const first = this.first[index]!;
    const last = this.last[index]!;
    if (last < first) return out;
    let byte = this.offsets[index]!;
    for (let column = first; column <= last; byte += 1) {
      const packed = this.cells[byte]!;
      out[column] = packed >> 4;
      column += 1;
      if (column <= last) out[column] = packed & 0x0f;
      column += 1;
    }
    return out;
  }

  /** The reference row a raster row is measured against, or null when it has none. */
  referenceRow(index: number): Uint8Array | null {
    if (!this.reference || !this.referenceCells) return null;
    const slot = this.reference[index]!;
    if (slot < 0) return null;
    const cached = this.referenceCache.get(slot);
    if (cached) return cached;
    const stride = (this.width + 1) >> 1;
    const out = new Uint8Array(this.width);
    let byte = slot * stride;
    for (let column = 0; column < this.width; byte += 1) {
      const packed = this.referenceCells[byte]!;
      out[column] = packed >> 4;
      column += 1;
      if (column < this.width) out[column] = packed & 0x0f;
      column += 1;
    }
    this.referenceCache.set(slot, out);
    return out;
  }

  referenceLabel(index: number): string {
    const slot = this.reference ? this.reference[index]! : -1;
    return slot < 0 ? "" : (this.header.references?.[slot]?.label ?? "");
  }
}

/** Coverage states for one row, at column resolution. */
export function coverageStates(row: Uint8Array, first: number, last: number): Uint8Array {
  const out = new Uint8Array(row.length);
  for (let column = 0; column < row.length; column += 1) {
    const code = row[column]!;
    if (isBase(code)) out[column] = COVERAGE.BASE;
    else if (code === AMBIGUOUS) out[column] = COVERAGE.AMBIGUOUS;
    else out[column] = column >= first && column <= last ? COVERAGE.GAP : COVERAGE.ABSENT;
  }
  return out;
}

function translate(a: number, b: number, c: number): string {
  return AMINO[(TCAG[a]! * 4 + TCAG[b]!) * 4 + TCAG[c]!]!;
}

/** Per-codon divergence states for one row, mirroring `divergence.measure`.
 *
 *  Three details are easy to get wrong and each is load-bearing:
 *
 *  1. The indel span comes from the JOINT comparable mask — columns where query AND
 *     reference both carry an unambiguous base — not from the query's own coverage.
 *     Against a union-coverage consensus the two differ at nearly every edge.
 *  2. A codon touched by both a deletion and an insertion is charged ONCE. The Python
 *     ORs the two masks before counting codons; here deletion wins the label, so the
 *     total still matches.
 *  3. Indels are only counted inside that span. Outside it the query simply has no
 *     material, which is missing data rather than a deletion.
 */
export function divergenceStates(
  row: Uint8Array,
  reference: Uint8Array | null,
  width: number,
): Uint8Array {
  const codons = Math.floor(width / 3);
  const out = new Uint8Array(codons);
  if (!reference) {
    out.fill(DIVERGENCE.NO_REFERENCE);
    return out;
  }

  let spanFirst = -1;
  let spanLast = -1;
  for (let column = 0; column < width; column += 1) {
    if (isBase(row[column]!) && isBase(reference[column]!)) {
      if (spanFirst < 0) spanFirst = column;
      spanLast = column;
    }
  }

  for (let codon = 0; codon < codons; codon += 1) {
    const at = codon * 3;
    let comparable = true;
    let deletion = false;
    let insertion = false;
    for (let k = 0; k < 3; k += 1) {
      const column = at + k;
      const q = row[column]!;
      const r = reference[column]!;
      if (!isBase(q) || !isBase(r)) comparable = false;
      if (column >= spanFirst && column <= spanLast && spanFirst >= 0) {
        if (r !== GAP && q === GAP) deletion = true;
        else if (q !== GAP && r === GAP) insertion = true;
      }
    }
    if (deletion) out[codon] = DIVERGENCE.DELETION;
    else if (insertion) out[codon] = DIVERGENCE.INSERTION;
    else if (!comparable) out[codon] = DIVERGENCE.UNCOMPARABLE;
    else {
      const same =
        row[at] === reference[at] &&
        row[at + 1] === reference[at + 1] &&
        row[at + 2] === reference[at + 2];
      if (same) out[codon] = DIVERGENCE.IDENTICAL;
      else {
        out[codon] =
          translate(row[at]!, row[at + 1]!, row[at + 2]!) ===
          translate(reference[at]!, reference[at + 1]!, reference[at + 2]!)
            ? DIVERGENCE.SYNONYMOUS
            : DIVERGENCE.NONSYNONYMOUS;
      }
    }
  }
  return out;
}

export interface RowCounts {
  synonymous: number;
  nonsynonymous: number;
  assessable: number;
  comparable: number;
  indelCodons: number;
}

/** Figure 1's numbers for one row, as sums over its own raster row.
 *
 *  This is the identity the sixth figure rests on, and the reason the divergence
 *  vocabulary has the states it has: a reader who zooms into one record is looking at
 *  the arithmetic behind its dot, not at a parallel measurement of it. */
export function rowCounts(states: Uint8Array): RowCounts {
  let synonymous = 0;
  let nonsynonymous = 0;
  let comparable = 0;
  let indelCodons = 0;
  for (let codon = 0; codon < states.length; codon += 1) {
    switch (states[codon]) {
      case DIVERGENCE.IDENTICAL:
        comparable += 1;
        break;
      case DIVERGENCE.SYNONYMOUS:
        comparable += 1;
        synonymous += 1;
        break;
      case DIVERGENCE.NONSYNONYMOUS:
        comparable += 1;
        nonsynonymous += 1;
        break;
      case DIVERGENCE.DELETION:
      case DIVERGENCE.INSERTION:
        indelCodons += 1;
        break;
      default:
        break;
    }
  }
  return {
    synonymous,
    nonsynonymous: nonsynonymous + indelCodons,
    assessable: comparable + indelCodons,
    comparable,
    indelCodons,
  };
}

export interface ColumnTrack {
  /** Records carrying an unambiguous base at each column — figure 1's denominator and
   *  figure 2's mask, per column, over exactly the rows in view. */
  covered: Int32Array;
  /** Of those, how many differ from their own reference. Empty for a non-coding
   *  region, where no figure resolves a reference. */
  differing: Int32Array;
}

/** The honest aggregate over every visible row.
 *
 *  The raster itself samples one record per pixel row once rows outnumber pixels; this
 *  does not. It is where the full population is represented, which is why it sits above
 *  the plot rather than being folded into it.
 */
export function columnTrack(block: AlignmentBlock, rows: number[]): ColumnTrack {
  const covered = new Int32Array(block.width);
  const differing = new Int32Array(block.width);
  for (const index of rows) {
    const row = block.row(index);
    const reference = block.referenceRow(index);
    const first = block.first[index]!;
    const last = block.last[index]!;
    for (let column = first; column <= last; column += 1) {
      const code = row[column]!;
      if (!isBase(code)) continue;
      covered[column]! += 1;
      if (reference && isBase(reference[column]!) && code !== reference[column]!) {
        differing[column]! += 1;
      }
    }
  }
  return { covered, differing };
}

/** Fetch and decode one region's container.
 *
 *  The gzip magic is sniffed rather than assumed. GitHub Pages and the dev server both
 *  serve `.bin.gz` as an opaque body, so the bytes arrive still compressed and this
 *  inflates them; a CDN that decides to set `Content-Encoding: gzip` would have the
 *  browser inflate first, and without this check that deploy would fail in a way local
 *  review could never reproduce.
 */
export async function loadAlignment(path: string): Promise<AlignmentBlock> {
  const response = await fetch(path, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
  let bytes = new Uint8Array(await response.arrayBuffer());
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) {
    const stream = new Response(bytes).body!.pipeThrough(new DecompressionStream("gzip"));
    bytes = new Uint8Array(await new Response(stream).arrayBuffer());
  }
  return decodeAlignment(bytes);
}

/** Container -> block. Split out from the fetch so it can be tested without a network. */
export function decodeAlignment(bytes: Uint8Array): AlignmentBlock {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const headerLength = view.getUint32(0, true);
  const header = JSON.parse(
    new TextDecoder().decode(bytes.subarray(4, 4 + headerLength)),
  ) as AlignmentHeader;

  const sections = new Map<string, Int32Array | Uint8Array>();
  let offset = 4 + headerLength;
  for (const section of header.sections) {
    sections.set(
      section.name,
      section.type === "i32"
        ? new Int32Array(bytes.buffer, bytes.byteOffset + offset, section.bytes / 4)
        : bytes.subarray(offset, offset + section.bytes),
    );
    offset += section.bytes;
  }
  if (offset !== bytes.length) {
    throw new Error(`alignment payload has ${bytes.length - offset} trailing bytes`);
  }
  return new AlignmentBlock(header, sections);
}
