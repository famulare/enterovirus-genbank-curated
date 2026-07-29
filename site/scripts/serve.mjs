/** Serve site/dist/ for local review. Development convenience only — nothing in
 *  the deploy path uses it. */

import { createReadStream } from "node:fs";
import { stat } from "node:fs/promises";
import { createServer } from "node:http";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";

const DIST = join(dirname(dirname(fileURLToPath(import.meta.url))), "dist");
const PORT = Number(process.env.PORT ?? 4173);

const TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

createServer(async (request, response) => {
  const url = new URL(request.url ?? "/", "http://localhost");
  // normalize + prefix check keeps `..` from escaping dist/.
  let path = join(DIST, normalize(decodeURIComponent(url.pathname)));
  if (!path.startsWith(DIST)) {
    response.writeHead(403).end("forbidden");
    return;
  }
  try {
    if ((await stat(path)).isDirectory()) path = join(path, "index.html");
  } catch {
    path = join(DIST, "index.html");
  }
  try {
    await stat(path);
  } catch {
    response.writeHead(404).end("not found");
    return;
  }
  response.writeHead(200, {
    "content-type": TYPES[extname(path)] ?? "application/octet-stream",
    "cache-control": "no-cache",
  });
  createReadStream(path).pipe(response);
}).listen(PORT, () => {
  console.log(`site/dist → http://localhost:${PORT}/`);
});
