"use client";

import { useSyncExternalStore } from "react";
import { todayIso } from "@/lib/format";

const noopSubscribe = () => () => {};

/**
 * The user's local date ("YYYY-MM-DD"), read on the client only.
 *
 * Returns null during prerender/hydration so a build-time or server-timezone
 * date is never baked into the HTML (Cache Components flags that as an error).
 */
export function useToday(): string | null {
  return useSyncExternalStore(noopSubscribe, () => todayIso(), () => null);
}
