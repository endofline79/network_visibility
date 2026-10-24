import { observationTime } from "./observationTime";
import type { Location } from "./types";
export type HistoryEntry = { lastSeen: string; until: number };
// Canonical area IDs survive screen grouping, zoom, selection and view changes.
export function updateHistory(
  history: Map<string, HistoryEntry>,
  initialized: { current: boolean },
  locations: Location[],
  nearLive: boolean,
  receivedAt: number,
) {
  const visibleIds = new Set(locations.map((a) => a.id));
  for (const [id, entry] of history) {
    if (receivedAt - Date.parse(entry.lastSeen) > 600000) history.delete(id);
    else if (!visibleIds.has(id)) entry.until = 0;
  }
  if (!nearLive) return;
  let valid = false;
  for (const a of locations) {
    const timestamp = observationTime(a.last_seen || "");
    if (!a.activity_id || timestamp === null || !a.last_seen) continue;
    valid = true;
    const old = history.get(a.id);
    if (old && timestamp <= (observationTime(old.lastSeen) || 0n)) continue;
    history.set(a.id, {
      lastSeen: a.last_seen,
      until: initialized.current ? receivedAt + 8000 : 0,
    });
  }
  while (history.size > 256) {
    const oldest = [...history.entries()].reduce((a, b) =>
      (observationTime(a[1].lastSeen) || 0n) <=
      (observationTime(b[1].lastSeen) || 0n)
        ? a
        : b,
    );
    history.delete(oldest[0]);
  }
  if (valid) initialized.current = true;
}
