"use client";

import { CheckCircle2, Circle, Moon, XCircle } from "lucide-react";
import Link from "next/link";
import type { PlannedSession } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { useFormat } from "@/lib/units";
import { WORKOUT_TYPES } from "@/lib/workout-types";

const STATUS = {
  completed: { icon: CheckCircle2, label: "Completed", className: "text-positive" },
  missed: { icon: XCircle, label: "Missed", className: "text-negative" },
  planned: { icon: Circle, label: "Planned", className: "text-ink-muted" },
  rest: { icon: Moon, label: "Rest day", className: "text-ink-muted" },
} as const;

/** Distinct icon shapes + text label (visible, or sr-only + tooltip when iconOnly): never colour alone. */
export function SessionStatus({ status, iconOnly = false }: {
  status: PlannedSession["status"];
  iconOnly?: boolean;
}) {
  const { icon: Icon, label, className } = STATUS[status];
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 text-[12px] font-medium ${className}`}
          title={iconOnly ? label : undefined}>
      <Icon aria-hidden className="size-3.5" />
      <span className={iconOnly ? "sr-only" : undefined}>{label}</span>
    </span>
  );
}

export function SessionCard({ session, isToday = false, showDescription = true, iconStatus = false }: {
  session: PlannedSession;
  isToday?: boolean;
  /** Hide the coaching notes (e.g. in short summaries). */
  showDescription?: boolean;
  /** Icon-only status for narrow grid cells. */
  iconStatus?: boolean;
}) {
  const f = useFormat();
  const type = session.type ? WORKOUT_TYPES[session.type] : null;
  const hasPace = session.target_fast_s_per_km != null && session.target_slow_s_per_km != null;

  return (
    <article
      className={`flex h-full flex-col gap-1.5 rounded-lg border p-3 ${
        isToday ? "border-ink bg-surface ring-1 ring-ink" : "border-line"
      } ${type ? "bg-surface" : "bg-canvas"}`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="whitespace-nowrap text-[12px] font-medium text-ink-muted">
          {isToday ? <span className="rounded bg-accent px-1.5 py-0.5 text-ink">Today</span>
                   : formatDate(session.date, { weekday: "short", day: "numeric" })}
        </p>
        <SessionStatus status={session.status} iconOnly={iconStatus} />
      </div>
      <h3 className="flex items-center gap-1.5 font-medium text-ink">
        {type && <span aria-hidden className="size-1.5 shrink-0 rounded-full" style={{ backgroundColor: type.color }} />}
        {session.title}
      </h3>
      {session.type && (
        <p className="text-[13px] tabular-nums text-ink">
          {f.distance(session.distance_m)}
          {hasPace && (
            <span className="block whitespace-nowrap text-ink-muted">
              {f.paceRange(session.target_fast_s_per_km!, session.target_slow_s_per_km!)}
            </span>
          )}
        </p>
      )}
      {showDescription && session.type && (
        <p className="text-[13px] leading-snug text-ink-muted">{session.description}</p>
      )}
      {session.completed_workout_id && (
        <Link href={`/workouts/${session.completed_workout_id}`}
              className="mt-auto pt-1 text-[13px] font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
          View run
        </Link>
      )}
    </article>
  );
}
