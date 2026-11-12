"use client";

import Link from "next/link";
import { Card, EmptyState, Pill, QueryState, TABLE_CELL as TD, TABLE_HEAD as TH } from "@/components/ui";
import type { BestEffort, PersonalBest } from "@/lib/api/client";
import { usePersonalBests } from "@/lib/api/hooks";
import { formatDate, formatDuration } from "@/lib/format";
import { useFormat } from "@/lib/units";

/** Fastest stretch of each standard distance inside any run, all-time and recent. */
export function PersonalBests({ className = "" }: { className?: string }) {
  const bests = usePersonalBests();
  return (
    <Card title="Personal bests" className={className} flush
          action={<span className="text-[13px] text-ink-muted">Fastest stretch inside any run</span>}>
      <QueryState query={bests}>
        {(rows) => {
          const found = rows.filter((r): r is PersonalBest & { all_time: BestEffort } => r.all_time != null);
          return found.length === 0
            ? <div className="p-5"><EmptyState message="No personal bests yet. Import runs recorded on Apple Watch to find your fastest 1K, mile, 5K and more." /></div>
            : <BestsTable rows={found} />;
        }}
      </QueryState>
    </Card>
  );
}

function BestsTable({ rows }: { rows: (PersonalBest & { all_time: BestEffort })[] }) {
  const f = useFormat();  // pace follows the km/mi toggle
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[560px] text-left">
        <caption className="sr-only">Personal best times by distance, with your best of the last 90 days</caption>
        <thead>
          <tr className="border-b border-line">
            <th scope="col" className={TH}>Distance</th>
            <th scope="col" className={`${TH} text-right`}>Best</th>
            <th scope="col" className={`${TH} text-right`}>Pace</th>
            <th scope="col" className={TH}>Set on</th>
            <th scope="col" className={`${TH} text-right`}>Last 90 days</th>
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map(({ key, label, all_time: best, recent }) => (
            <tr key={key} className="border-b border-line last:border-0">
              <th scope="row" className={`${TD} font-medium text-ink`}>{label}</th>
              <td className={`${TD} text-right text-ink`}>{formatDuration(best.duration_s)}</td>
              <td className={`${TD} text-right text-ink-muted`}>{f.pace(best.pace_s_per_km)}</td>
              <td className={TD}>
                <Link href={`/workouts/${best.workout_id}`}
                      className="text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                  {formatDate(best.date, { month: "short", day: "numeric", year: "numeric" })}
                </Link>
              </td>
              <td className={`${TD} text-right text-ink`}>
                <RecentBest best={best} recent={recent} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RecentBest({ best, recent }: { best: BestEffort; recent: BestEffort | null }) {
  if (recent == null) return <span className="text-ink-muted">–</span>;
  const isPb = recent.workout_id === best.workout_id && recent.duration_s === best.duration_s;
  return (
    <span className="inline-flex items-center gap-2">
      {isPb && <Pill tone="positive">PB</Pill>}
      {formatDuration(recent.duration_s)}
    </span>
  );
}
