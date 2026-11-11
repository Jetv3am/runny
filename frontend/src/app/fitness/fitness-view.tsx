"use client";

import { useState } from "react";
import { HealthTrendChart } from "@/components/charts/health-trend-chart";
import { LoadChart } from "@/components/charts/load-chart";
import { SegmentedControl } from "@/components/segmented-control";
import { Card, Delta, PageHeader, Pill, QueryState, Stat, StatGroup, type Tone } from "@/components/ui";
import { useDailyMetrics, useFitnessSummary, useHealthMetrics } from "@/lib/api/hooks";
import { formatSigned } from "@/lib/format";

type Range = "30" | "90" | "180";
const RANGES = [
  { value: "30", label: "30d" },
  { value: "90", label: "90d" },
  { value: "180", label: "180d" },
] as const;

const FORM_BANDS: { label: string; range: string; meaning: string; tone: Tone }[] = [
  { label: "Fresh", range: "Above +5", meaning: "Rested. Good for racing or a breakthrough session.", tone: "positive" },
  { label: "Neutral", range: "−10 to +5", meaning: "Balanced. Maintaining fitness.", tone: "neutral" },
  { label: "Productive", range: "−30 to −10", meaning: "Building fitness. Normal during a training block.", tone: "info" },
  { label: "Overreaching", range: "Below −30", meaning: "High injury and illness risk. Back off.", tone: "negative" },
];

export function FitnessView() {
  const [range, setRange] = useState<Range>("90");
  const summary = useFitnessSummary();
  const load = useDailyMetrics(Number(range));
  const vo2 = useHealthMetrics("vo2max");
  const rhr = useHealthMetrics("resting_hr");

  return (
    <>
      <PageHeader title="Fitness" description="How your body is responding to training." />

      <QueryState query={summary}>
        {(s) => (
          <StatGroup>
            <Stat label="VDOT" value={s.vdot ?? "–"}
                  delta={s.vdot_change_28d != null && <Delta value={s.vdot_change_28d} />}
                  hint={s.vdot_change_28d != null ? "vs 28 days ago" : "No race efforts yet"} />
            <Stat label="Fitness (CTL)" value={s.ctl.toFixed(0)} hint="42-day load" />
            <Stat label="Fatigue (ATL)" value={s.atl.toFixed(0)} hint="7-day load" />
            <Stat label="Form (TSB)" value={formatSigned(s.tsb)} hint={s.form} />
          </StatGroup>
        )}
      </QueryState>

      <div className="mt-8">
        <QueryState query={load}>
          {(data) => (
            <LoadChart data={data} height={300}
                       action={<SegmentedControl<Range> label="Date range" options={RANGES} value={range} onChange={setRange} size="sm" />} />
          )}
        </QueryState>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <QueryState query={vo2}>
          {(data) => <HealthTrendChart title="VO₂max (Apple Watch)" data={data} higherIsBetter />}
        </QueryState>
        <QueryState query={rhr}>
          {(data) => <HealthTrendChart title="Resting heart rate" data={data} higherIsBetter={false} />}
        </QueryState>
      </div>

      <Card title="Reading your form" className="mt-8" flush>
        <p className="px-5 pt-4 text-[13px] text-ink-muted">
          Fitness (CTL) is your 6-week load, fatigue (ATL) your last week, and form (TSB) the difference between them.
        </p>
        <table className="mt-2 w-full text-left">
          <caption className="sr-only">Form bands</caption>
          <thead>
            <tr className="border-b border-line">
              <th scope="col" className="px-5 py-2.5 text-[12px] font-medium text-ink-muted">Form</th>
              <th scope="col" className="px-5 py-2.5 text-[12px] font-medium text-ink-muted">TSB range</th>
              <th scope="col" className="px-5 py-2.5 text-[12px] font-medium text-ink-muted">What it means</th>
            </tr>
          </thead>
          <tbody>
            {FORM_BANDS.map((band) => (
              <tr key={band.label} className="border-b border-line last:border-0">
                <th scope="row" className="px-5 py-3 font-normal"><Pill tone={band.tone}>{band.label}</Pill></th>
                <td className="px-5 py-3 tabular-nums text-ink">{band.range}</td>
                <td className="px-5 py-3 text-ink-muted">{band.meaning}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </>
  );
}
