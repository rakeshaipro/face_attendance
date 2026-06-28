/** Non-component helpers for the settings editor. Kept in a separate
 * file from `SettingsField.tsx` so the fast-refresh plugin only sees
 * component exports there. */
import type { SettingUpdateResult } from "@/lib/types";

/** Turn the server's `[{key, ok, error}]` payload into a
 * `Record<key, error>` for inline display. */
export function resultsToErrorMap(
  results: SettingUpdateResult[],
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of results) {
    if (!r.ok && r.error) out[r.key] = r.error;
  }
  return out;
}
