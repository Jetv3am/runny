"use client";

import { ArrowLeft } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { SplitsChart } from "@/components/charts/splits-chart";
import { EmptyState, PageHeader, QueryState, Stat, StatGroup, TypeBadge } from "@/components/ui";
import { useWorkout } from "@/lib/api/hooks";
import { formatDuration, formatLongDate } from "@/lib/format";
import { useFormat } from "@/lib/units";

/** Formats a value, or shows a dash when it wasn't recorded (never a misleading 0). */
function orDash(value: number | null | undefined, format: (v: number) => string, dash = "–"): string {
  return value == null ? dash : format(value);
}

export function WorkoutDetailView() {
  const { id } = useParams<{ id: string }>();
  const workout = useWorkout(id);
  const f = useFormat();

  return (
    <QueryState query={workout}>
      {(w) => (
        <>
          <PageHeader
            eyebrow={
              <Link href="/workouts" className="inline-flex items-center gap-1 hover:text-ink">
                <ArrowLeft aria-hidden className="size-3.5" /> Workouts
              </Link>
            }
            title={w.title}
            description={<span className="inline-flex items-center gap-2">{formatLongDate(w.start_at)} <TypeBadge type={w.type} /></span>}
          />
          <div className="space-y-4">
            <StatGroup>
              <Stat label="Distance" value={f.distance(w.distance_m, 2)} />
              <Stat label="Time" value={formatDuration(w.duration_s)} />
              <Stat label="Avg pace" value={f.pace(w.pace_s_per_km)} />
              <Stat label="Avg / max HR" value={`${w.avg_hr ?? "–"} / ${w.max_hr ?? "–"}`} hint="bpm" />
            </StatGroup>
            <StatGroup>
              <Stat label="Training load" value={w.trimp.toFixed(0)} hint="TRIMP" />
              <Stat label="Elevation gain" value={orDash(w.elevation_gain_m, (m) => `${m.toFixed(0)} m`)} />
              <Stat label="Cadence" value={w.avg_cadence ?? "–"} hint="steps/min" />
              <Stat label="Temperature" value={orDash(w.temperature_c, (c) => `${c.toFixed(0)}°C`)}
                    hint={orDash(w.energy_kcal, (kcal) => `${kcal.toFixed(0)} kcal`, "")} />
            </StatGroup>
          </div>
          <div className="mt-8">
            {w.splits.length > 0 ? <SplitsChart workout={w} /> : (
              <EmptyState message="Per-kilometre splits need GPS and heart-rate samples from the export. They arrive in Phase 2." />
            )}
          </div>
        </>
      )}
    </QueryState>
  );
}
