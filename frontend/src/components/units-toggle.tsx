"use client";

import { SegmentedControl } from "@/components/segmented-control";
import type { Units } from "@/lib/format";
import { useUnits } from "@/lib/units";

const OPTIONS = [
  { value: "metric", label: "km" },
  { value: "imperial", label: "mi" },
] as const;

export function UnitsToggle({ size }: { size?: "sm" | "md" }) {
  const { units, setUnits } = useUnits();
  return <SegmentedControl<Units> label="Distance units" options={OPTIONS} value={units} onChange={setUnits} size={size} />;
}
