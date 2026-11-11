"use client";

import { Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { WeeklyVolume } from "@/lib/api/client";
import { formatDate, formatDuration } from "@/lib/format";
import { useFormat } from "@/lib/units";
import { AXIS_PROPS, CHART, ChartFrame, TOOLTIP_PROPS } from "./chart-frame";

export function WeeklyVolumeChart({ data }: { data: WeeklyVolume[] }) {
  const f = useFormat();
  const points = data.map((w) => ({ ...w, value: Number(f.distanceValue(w.distance_m).toFixed(1)) }));
  const peak = data.reduce((max, w) => (w.distance_m > max.distance_m ? w : max), data[0]);
  const summary = peak
    ? `Last ${data.length} weeks. Biggest week: ${f.distance(peak.distance_m)} (week of ${formatDate(peak.week_start)}). ` +
      "The current week is highlighted."
    : "No weekly volume yet.";
  const currentIndex = points.length - 1;

  return (
    <ChartFrame
      title="Weekly volume"
      summary={summary}
      height={220}
      table={{
        columns: ["Week of", "Distance", "Time", "Runs"],
        rows: [...data].reverse().map((w) => [
          formatDate(w.week_start), f.distance(w.distance_m), formatDuration(w.duration_s), w.runs,
        ]),
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="week_start" tickFormatter={(d: string) => formatDate(d)} {...AXIS_PROPS} />
          <YAxis unit={` ${f.distanceUnit}`} width={64} {...AXIS_PROPS} />
          <Tooltip
            labelFormatter={(d) => `Week of ${formatDate(String(d))}`}
            formatter={(v) => [`${v} ${f.distanceUnit}`, "Distance"]}
            {...TOOLTIP_PROPS}
            cursor={{ fill: "var(--color-hover)" }}
          />
          <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={36} isAnimationActive={false}>
            {points.map((point, i) => (
              <Cell
                key={point.week_start}
                fill={i === currentIndex ? CHART.accentFill : CHART.primary}
                stroke={i === currentIndex ? CHART.accentStroke : undefined}
              />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
