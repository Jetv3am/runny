"use client";

import { FlaskConical } from "lucide-react";
import { PredictionStrip } from "@/components/prediction-card";
import { Card, PageHeader, Pill, QueryState, Stat, StatGroup } from "@/components/ui";
import { useCurrentPlan, useRacePredictions } from "@/lib/api/hooks";
import { daysUntil, formatDate, formatDuration } from "@/lib/format";

const SOURCE_LABEL = {
  vdot_baseline: "Physiology baseline · Daniels VDOT",
  ml: "Personalised ML model",
} as const;

const STEPS = [
  { title: "Estimate VDOT", body: "From your recent race efforts, weighting newer races more heavily." },
  { title: "Convert", body: "Daniels' equations turn that VDOT into equivalent times for every distance." },
  { title: "Personalise · Phase 3", body: "An ML model learns how you differ from the formula. It replaces the baseline only if it's more accurate on your own races." },
];

export function PredictionsView() {
  const predictions = useRacePredictions();
  const plan = useCurrentPlan();

  return (
    <>
      <PageHeader
        title="Race predictions"
        description="What you could run today, with a realistic range."
        actions={predictions.data && (
          <Pill tone="info"><FlaskConical aria-hidden className="size-3.5" /> {SOURCE_LABEL[predictions.data.source]}</Pill>
        )}
      />

      <QueryState query={predictions}>
        {(p) => (
          <>
            <PredictionStrip predictions={p.predictions} detailed />
            <p className="mt-3 text-[13px] text-ink-muted">
              VDOT {p.vdot}. The bar spans a great day (left) to a tough one (right). Longer races have wider
              ranges because they depend more on endurance and race-specific training.
            </p>
          </>
        )}
      </QueryState>

      <QueryState query={plan}>
        {({ goal }) => {
          const gap = goal.target_time_s != null && goal.predicted_time_s != null
            ? goal.predicted_time_s - goal.target_time_s : null;
          return (
            <section className="mt-8" aria-labelledby="goal-heading">
              <h2 id="goal-heading" className="mb-3 text-[16px] font-medium tracking-[-0.01em] text-ink">
                Goal race · {goal.race_label}
              </h2>
              <StatGroup columns={3}>
                <Stat label="Race day" value={formatDate(goal.race_date, { month: "short", day: "numeric" })}
                      hint={`${daysUntil(goal.race_date)} days to go`} />
                <Stat label="Target" value={goal.target_time_s ? formatDuration(goal.target_time_s) : "–"} />
                <Stat
                  label="Predicted today"
                  value={goal.predicted_time_s ? formatDuration(goal.predicted_time_s) : "–"}
                  delta={gap != null && (
                    <Pill tone={gap <= 0 ? "positive" : "warning"}>
                      {gap <= 0 ? `${formatDuration(-gap)} ahead` : `${formatDuration(gap)} to find`}
                    </Pill>
                  )}
                />
              </StatGroup>
            </section>
          );
        }}
      </QueryState>

      <Card title="How predictions work" className="mt-8">
        <ol className="grid gap-6 md:grid-cols-3">
          {STEPS.map((step, i) => (
            <li key={step.title}>
              <span aria-hidden className="grid size-6 place-items-center rounded-md bg-hover text-[12px] font-medium text-ink">{i + 1}</span>
              <h3 className="mt-3 font-medium text-ink">{step.title}</h3>
              <p className="mt-1 text-[13px] leading-relaxed text-ink-muted">{step.body}</p>
            </li>
          ))}
        </ol>
      </Card>
    </>
  );
}
