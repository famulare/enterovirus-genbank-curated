/** Fetching the built artifacts, once each.
 *
 *  Four chapters read three files between them: the two scatters share a panel file and
 *  the two trees share a tree file. Without a cache each pair would fetch its source
 *  twice on every selection change, so the cache is keyed by path rather than owned by
 *  a chapter.
 */

const pending = new Map<string, Promise<unknown>>();

export function loadFile<T>(path: string): Promise<T> {
  const existing = pending.get(path);
  if (existing) return existing as Promise<T>;
  const request = fetch(path, { cache: "no-cache" }).then(async (response) => {
    if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`);
    return response.json();
  });
  // A rejection must not be remembered as the answer, or one dropped request would
  // keep failing for the rest of the session.
  request.catch(() => pending.delete(path));
  pending.set(path, request);
  return request as Promise<T>;
}
