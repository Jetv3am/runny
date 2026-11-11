"use client";

import { ChevronDown } from "lucide-react";
import { SessionCard } from "@/components/session-card";
import { Card, PageHeader, Pill, QueryState, Stat, StatGroup, type Tone } from "@/components/ui";
import type { PlanWeek } from "@/lib/api/client";
import { useCurrentPlan } from "@/lib/api/hooks";
import { daysUntil, formatDate, formatDuration } from "@/lib/format";
import { useFormat } from "@/lib/units";
import { useToday } from "@/lib/use-today";

const PHASES: Record<PlanWeek["phase"], { label: string; tone: Tone }> = {
  base: { label: "Base", tone: "positive" },
  build: { label: "Build", tone: "warning" },
  peak: { label: "Peak", tone: "negative" },
  taper: { label: "Taper", tone: "info" },
};

const RULES = [
  "Phases go Base → Build → Peak → Taper, sized to the weeks left.",
  "Weekly volume rises at most 10%, with a lighter week every fourth week.",
  "About 80% easy running; at most two hard sessions a week, never back-to-back.",
  "Paces come from your current VDOT, so they update as you get fitter.",
];

function WeekSection({ week, today }: { week: PlanWeek; today: string | null }) {
  const f = useFormat();
  const end = week.sessions.at(-1)?.date ?? week.start_date;
  const isCurrent = today != null && week.start_date <= today && today <= end;
  const isPast = today != null && end < today;
  const runs = week.sessions.filter((s) => s.type);
  const done = runs.filter((s) => s.status === "completed").length;
  const phase = PHASES[week.phase];

  return (
    <details open={isCurrent || (!isPast && week.index < 2)}
             className="group border-b border-line last:border-0">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 px-5 py-3.5 hover:bg-hover">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="w-16 font-medium text-ink">Week {week.index + 1}</h2>
          <span className="w-32 text-[13px] tabular-nums text-ink-muted">
            {formatDate(week.start_date)} – {formatDate(end)}
          </span>
          <Pill tone={phase.tone}>{phase.label}</Pill>
          {isCurrent && <Pill tone="accent">This week</Pill>}
        </div>
        <div className="flex items-center gap-5 text-[13px] tabular-nums text-ink">
          {(isPast || isCurrent) && <span className="text-ink-muted">{done}/{runs.length} done</span>}
          <span className="w-14 text-right font-medium">{f.distance(week.target_distance_m, 0)}</span>
          <ChevronDown aria-hidden className="size-4 text-ink-muted transition-transform group-open:rotate-180" />
        </div>
      </summary>
      <ol className="grid gap-2 bg-canvas/60 px-5 pb-5 pt-1 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
        {week.sessions.map((session) => (
          <li key={session.date}>
            <SessionCard session={session} isToday={session.date === today} iconStatus />
          </li>
        ))}
      </ol>
    </details>
  );
}

export function PlanView() {
  const plan = useCurrentPlan();
  const f = useFormat();
  const today = useToday();

  return (
    <QueryState query={plan}>
      {({ goal, weeks }) => (
        <>
          <PageHeader
            title="Training plan"
            description={`${weeks.length}-week plan for ${goal.race_label}. Built by rules, adapted as you train.`}
          />
          <StatGroup>
            <Stat label="Goal race" value={f.distance(goal.distance_m)}
                  hint={formatDate(goal.race_date, { weekday: "short", month: "short", day: "numeric" })} />
            <Stat label="Countdown" value={`${daysUntil(goal.race_date)} days`} />
            <Stat label="Target time" value={goal.target_time_s ? formatDuration(goal.target_time_s) : "–"} />
            <Stat label="Predicted today" value={goal.predicted_time_s ? formatDuration(goal.predicted_time_s) : "–"}
                  hint="from current VDOT" />
          </StatGroup>

          <Card title="Schedule" className="mt-8" flush>
            {weeks.map((week) => <WeekSection key={week.index} week={week} today={today} />)}
          </Card>

          <Card title="How this plan is built" className="mt-4">
            <ul className="grid gap-x-8 gap-y-2 text-[13px] text-ink-muted md:grid-cols-2">
              {RULES.map((rule) => (
                <li key={rule} className="flex gap-2">
                  <span aria-hidden className="mt-1.5 size-1 shrink-0 rounded-full bg-ink" />{rule}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </QueryState>
  );
}
