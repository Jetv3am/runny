import type { WorkoutType } from "@/lib/api/client";

/**
 * Labels and dot colours per workout type - one source for badges, charts, and the plan.
 * Dots always sit next to a text label, so colour is never the only signal.
 */
export const WORKOUT_TYPES: Record<WorkoutType, { label: string; color: string }> = {
  easy: { label: "Easy", color: "#2f9e5b" },
  long: { label: "Long", color: "#2563eb" },
  tempo: { label: "Tempo", color: "#d97706" },
  interval: { label: "Interval", color: "#dc2626" },
  recovery: { label: "Recovery", color: "#78716c" },
  race: { label: "Race", color: "#7c3aed" },
};

export const WORKOUT_TYPE_KEYS = Object.keys(WORKOUT_TYPES) as WorkoutType[];
