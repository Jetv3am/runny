/**
 * The single place where numbers become text. Backend units are always
 * metres, seconds, and seconds-per-km; conversion happens here only.
 */

export type Units = "metric" | "imperial";

const METRES_PER_MILE = 1609.344;

export function formatDistance(metres: number, units: Units, digits = 1): string {
  if (units === "imperial") return `${(metres / METRES_PER_MILE).toFixed(digits)} mi`;
  return `${(metres / 1000).toFixed(digits)} km`;
}

export function distanceValue(metres: number, units: Units): number {
  return units === "imperial" ? metres / METRES_PER_MILE : metres / 1000;
}

export function distanceUnit(units: Units): string {
  return units === "imperial" ? "mi" : "km";
}

/** Seconds -> "1:02:03" or "4:05". */
export function formatDuration(totalSeconds: number): string {
  const s = Math.round(totalSeconds);
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  const mm = hours ? String(minutes).padStart(2, "0") : String(minutes);
  const ss = String(seconds).padStart(2, "0");
  return hours ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
}

function paceValue(secondsPerKm: number, units: Units): number {
  return units === "imperial" ? secondsPerKm * (METRES_PER_MILE / 1000) : secondsPerKm;
}

/** Pace without unit suffix, e.g. "4:35". */
export function formatPaceShort(secondsPerKm: number, units: Units): string {
  return formatDuration(paceValue(secondsPerKm, units));
}

export function formatPace(secondsPerKm: number, units: Units): string {
  return `${formatPaceShort(secondsPerKm, units)} /${distanceUnit(units)}`;
}

export function formatPaceRange(fast: number, slow: number, units: Units): string {
  return `${formatPaceShort(fast, units)}–${formatPaceShort(slow, units)} /${distanceUnit(units)}`;
}

/** Parse "YYYY-MM-DD" as a *local* date (new Date("2026-01-02") would be UTC midnight). */
export function parseLocalDate(isoDate: string): Date {
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

/** Today's local date as "YYYY-MM-DD" (comparable with API date strings). */
export function todayIso(now: Date = new Date()): string {
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const dd = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${mm}-${dd}`;
}

function toDate(value: string): Date {
  return value.length === 10 ? parseLocalDate(value) : new Date(value);
}

export function formatDate(value: string, options: Intl.DateTimeFormatOptions = {
  month: "short", day: "numeric",
}): string {
  return toDate(value).toLocaleDateString(undefined, options);
}

export function formatLongDate(value: string): string {
  return formatDate(value, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
}

export function formatSigned(value: number, digits = 0): string {
  const fixed = value.toFixed(digits);
  return value > 0 ? `+${fixed}` : fixed;
}

export function formatBytes(bytes: number): string {
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function daysUntil(isoDate: string, from: Date = new Date()): number {
  const target = parseLocalDate(isoDate);
  const start = new Date(from.getFullYear(), from.getMonth(), from.getDate());
  return Math.round((target.getTime() - start.getTime()) / 86_400_000);
}
