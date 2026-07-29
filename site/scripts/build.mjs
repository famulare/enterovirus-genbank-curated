/** Build site/dist/ — the directory GitHub Pages publishes.
 *
 * Bundles the TypeScript, copies the stylesheets and the HTML, and copies the
 * committed data artifacts. It deliberately does NOT run the Python pipeline: the
 * deploy workflow must not need a bioinformatics toolchain, and the data artifacts
 * are committed and hash-gated instead. `uv run site/pipeline/cli.py check`
 * enforces that they are current.
 *
 * All asset references are relative, because Pages serves this under
 * /enterovirus-genbank-curated/ rather than at a domain root.
 */

import { cp, mkdir, readdir, rm, stat, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import * as esbuild from "esbuild";

const SITE = dirname(dirname(fileURLToPath(import.meta.url)));
const SRC = join(SITE, "src");
const DIST = join(SITE, "dist");
const DATA = join(SITE, "data");

const REQUIRED_DATA = ["summary.json", "manifest.json"];

async function main() {
  for (const name of REQUIRED_DATA) {
    try {
      await stat(join(DATA, name));
    } catch {
      throw new Error(
        `site/data/${name} is missing. Build it first:\n` +
          `  uv run site/pipeline/cli.py build`,
      );
    }
  }

  await rm(DIST, { recursive: true, force: true });
  await mkdir(DIST, { recursive: true });

  const result = await esbuild.build({
    entryPoints: [join(SRC, "app.ts")],
    outfile: join(DIST, "app.js"),
    bundle: true,
    format: "iife",
    target: "es2022",
    minify: true,
    sourcemap: false,
    legalComments: "none",
    metafile: true,
  });

  await cp(join(SRC, "index.html"), join(DIST, "index.html"));
  await cp(join(SRC, "app.css"), join(DIST, "app.css"));
  await cp(join(SITE, "tokens.css"), join(DIST, "tokens.css"));
  // Deliberately no 404.html. All state lives in the URL hash, so there are no
  // path-based routes to recover, and a copied index.html served from a deep path
  // would resolve its relative asset references against the wrong directory.
  //
  // Belt and braces: the Actions deploy does not run Jekyll, but if the Pages
  // source is ever switched back to a branch, Jekyll would drop underscore paths.
  await writeFile(join(DIST, ".nojekyll"), "");
  // `recursive` so the per-selection panels/ subdirectory comes along.
  await cp(DATA, join(DIST, "data"), { recursive: true });

  const bundle = Object.values(result.metafile.outputs)[0];
  console.log(`dist/app.js  ${(bundle.bytes / 1024).toFixed(1)} KiB`);
  for (const name of await readdir(DIST)) {
    if (name !== "app.js") console.log(`dist/${name}`);
  }
}

main().catch((error) => {
  console.error(error.message ?? error);
  process.exit(1);
});
