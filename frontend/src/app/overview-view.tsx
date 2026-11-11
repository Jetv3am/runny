"use client";

import { ArrowRight, MessageCircle, Sparkles } from "lucide-react";
import { LoadChart } from "@/components/charts/load-chart";
import { ReadinessRing } from "@/components/charts/readiness-ring";
import { PredictionStrip } from "@/components/prediction-card";
import { SessionCard } from "@/components/session-card";
import { ButtonLink, Card, Delta, PageHeader, QueryState, Stat, StatGroup, TextLink } from "@/components/ui";
import { WorkoutTable } from "@/components/workout-table";
import {
  useCurrentPlan,
  useDailyMetrics,
  useFitnessSummary,
  useRacePredictions,
  useWorkouts,
} from "@/lib/api/hooks";
import { formatLongDate, formatSigned } from "@/lib/format";
import { useFormat } from "@/lib/units";
import { useToday } from "@/lib/use-today";

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

export function OverviewView() {
  const f = useFormat();
  const summary = useFitnessSummary();
  const load = useDailyMetrics(90);
  const plan = useCurrentPlan();
  const predictions = useRacePredictions();
  const recent = useWorkouts({ limit: 5, offset: 0 });
  const today = useToday();
  const firstName = summary.data?.athlete_name.split(" ")[0];

  return (
    <>
      <PageHeader
        eyebrow={today ? formatLongDate(today) : undefined}
        title={firstName && today ? `${greeting()}, ${firstName}` : "Overview"}
        actions={
          <>
            <ButtonLink href="/plan">View plan</ButtonLink>
            <ButtonLink href="/coach" variant="primary"><MessageCircle aria-hidden className="size-4" /> Ask coach</ButtonLink>
          </>
        }
      />

      <QueryState query={summary}>
        {(s) => (
          <div className="space-y-4">
            <StatGroup>
              <Stat label="VDOT" value={s.vdot ?? "–"}
                    delta={s.vdot_change_28d != null && <Delta value={s.vdot_change_28d} />}
                    hint="vs 28 days ago" />
              <Stat label="Fitness (CTL)" value={s.ctl.toFixed(0)} hint="42-day training load" />
              <Stat label="Form (TSB)" value={formatSigned(s.tsb)} hint={s.form} />
              <Stat label="This week" value={f.distance(s.week_distance_m)}
                    hint={`${s.week_runs} run(s) · avg ${f.distance(s.avg_week_distance_4w_m, 0)}/wk`} />
            </StatGroup>

            <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
              <Card><ReadinessRing score={s.readiness} label={s.readiness_label} /></Card>
              {/* Insight banner: the one place lime is used as a large surface. */}
              <section className="flex flex-col justify-between gap-3 rounded-xl bg-accent-soft p-5">
                <div>
                  <p className="flex items-center gap-1.5 text-[13px] font-medium text-ink">
                    <Sparkles aria-hidden className="size-4" /> Coach briefing
                  </p>
                  <p className="mt-2 text-[15px] leading-relaxed text-ink">{s.briefing}</p>
                </div>
                <TextLink href="/coach">Ask a follow-up</TextLink>
              </section>
            </div>
          </div>
        )}
      </QueryState>

      <div className="mt-8 grid gap-4 xl:grid-cols-[1.6fr_1fr]">
        <QueryState query={load}>{(data) => <LoadChart data={data} />}</QueryState>
        <Card title="Up next" action={<TextLink href="/plan">Full plan</TextLink>}>
          <QueryState query={plan}>
            {(p) => {
              const upcoming = p.weeks.flatMap((w) => w.sessions)
                .filter((s) => today && s.date >= today && s.type).slice(0, 3);
              return (
                <ul className="space-y-2">
                  {upcoming.map((s) => (
                    <li key={s.date}><SessionCard session={s} isToday={s.date === today} showDescription={false} /></li>
                  ))}
                </ul>
              );
            }}
          </QueryState>
        </Card>
      </div>

      <section className="mt-8" aria-labelledby="predictions-heading">
        <div className="mb-3 flex items-center justify-between">
          <h2 id="predictions-heading" className="text-[16px] font-medium tracking-[-0.01em] text-ink">Race predictions</h2>
          <TextLink href="/predictions">Details <ArrowRight aria-hidden className="inline size-3.5" /></TextLink>
        </div>
        <QueryState query={predictions}>{(p) => <PredictionStrip predictions={p.predictions} />}</QueryState>
      </section>

      <Card title="Recent workouts" className="mt-8" flush action={<TextLink href="/workouts">All workouts</TextLink>}>
        <QueryState query={recent}>
          {(page) => <WorkoutTable workouts={page.items} caption="Five most recent workouts" />}
        </QueryState>
      </Card>
    </>
  );
}
