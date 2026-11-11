"use client";

import { createContext, useCallback, useContext, useMemo, useSyncExternalStore } from "react";
import * as fmt from "@/lib/format";
import type { Units } from "@/lib/format";

const STORAGE_KEY = "rc-units";
const listeners = new Set<() => void>();

function readUnits(): Units {
  return localStorage.getItem(STORAGE_KEY) === "imperial" ? "imperial" : "metric";
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

type UnitsContextValue = {
  units: Units;
  setUnits: (units: Units) => void;
};

const UnitsContext = createContext<UnitsContextValue | null>(null);

export function UnitsProvider({ children }: { children: React.ReactNode }) {
  const units = useSyncExternalStore(subscribe, readUnits, () => "metric" as Units);
  const setUnits = useCallback((next: Units) => {
    localStorage.setItem(STORAGE_KEY, next);
    listeners.forEach((notify) => notify());
  }, []);
  const value = useMemo(() => ({ units, setUnits }), [units, setUnits]);
  return <UnitsContext value={value}>{children}</UnitsContext>;
}

export function useUnits(): UnitsContextValue {
  const ctx = useContext(UnitsContext);
  if (!ctx) throw new Error("useUnits must be used inside <UnitsProvider>");
  return ctx;
}

/** Formatters pre-bound to the user's unit preference. */
export function useFormat() {
  const { units } = useUnits();
  return useMemo(
    () => ({
      units,
      distance: (m: number, digits?: number) => fmt.formatDistance(m, units, digits),
      distanceValue: (m: number) => fmt.distanceValue(m, units),
      distanceUnit: fmt.distanceUnit(units),
      pace: (s: number) => fmt.formatPace(s, units),
      paceShort: (s: number) => fmt.formatPaceShort(s, units),
      paceRange: (fast: number, slow: number) => fmt.formatPaceRange(fast, slow, units),
    }),
    [units],
  );
}
