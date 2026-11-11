"use client";

import Link from "next/link";
import type { WorkoutSummary } from "@/lib/api/client";
import { formatDate, formatDuration } from "@/lib/format";
import { useFormat } from "@/lib/units";
import { TypeBadge } from "@/components/ui";

const TH = "px-5 py-2.5 text-[12px] font-medium text-ink-muted";
const TD = "px-5 py-3";

/** Dense, hairline-divided table. Designed to sit edge-to-edge inside a `flush` Card. */
export function WorkoutTable({ workouts, caption }: { workouts: WorkoutSummary[]; caption: string }) {
  const f = useFormat();
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-left">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className={TH}>Date</th>
            <th scope="col" className={TH}>Workout</th>
            <th scope="col" className={TH}>Type</th>
            <th scope="col" className={`${TH} text-right`}>Distance</th>
            <th scope="col" className={`${TH} text-right`}>Time</th>
            <th scope="col" className={`${TH} text-right`}>Pace</th>
            <th scope="col" className={`${TH} text-right`}>Avg HR</th>
            <th scope="col" className={`${TH} text-right`}>Load</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {workouts.map((w) => (
            <tr key={w.id} className="group border-b border-line last:border-0 hover:bg-hover">
              <td className={`${TD} whitespace-nowrap text-ink-muted`}>
                {formatDate(w.start_at, { weekday: "short", month: "short", day: "numeric" })}
              </td>
              <td className={TD}>
                <Link href={`/workouts/${w.id}`} className="font-medium text-ink group-hover:underline underline-offset-4">
                  {w.title}
                </Link>
              </td>
              <td className={TD}><TypeBadge type={w.type} /></td>
              <td className={`${TD} text-right text-ink`}>{f.distance(w.distance_m, 2)}</td>
              <td className={`${TD} text-right text-ink`}>{formatDuration(w.duration_s)}</td>
              <td className={`${TD} text-right text-ink`}>{f.pace(w.pace_s_per_km)}</td>
              <td className={`${TD} text-right text-ink-muted`}>{w.avg_hr ?? "–"}</td>
              <td className={`${TD} text-right text-ink`}>{w.trimp.toFixed(0)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
