"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { DailyMetric } from "@/lib/api/client";
import { formatDate, formatSigned } from "@/lib/format";
import { AXIS_PROPS, CHART, ChartFrame, LEGEND_PROPS, TOOLTIP_PROPS } from "./chart-frame";

export function LoadChart({ data, height, action }: {
  data: DailyMetric[];
  height?: number;
  action?: React.ReactNode;
}) {
  const last = data.at(-1);
  const first = data[0];
  const summary = last && first
    ? `Fitness (CTL) moved from ${first.ctl.toFixed(0)} to ${last.ctl.toFixed(0)} over ${data.length} days. ` +
      `Fatigue (ATL) is ${last.atl.toFixed(0)} and form (TSB) is ${formatSigned(last.tsb)}.`
    : "No training load data yet.";

  return (
    <ChartFrame
      title="Training load"
      summary={summary}
      height={height}
      action={action}
      table={{
        columns: ["Date", "Fitness (CTL)", "Fatigue (ATL)", "Form (TSB)", "TRIMP"],
        rows: [...data].reverse().map((d) => [
          formatDate(d.date), d.ctl.toFixed(1), d.atl.toFixed(1), formatSigned(d.tsb, 1), d.trimp.toFixed(0),
        ]),
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={(d: string) => formatDate(d)} minTickGap={32} {...AXIS_PROPS} />
          <YAxis {...AXIS_PROPS} />
          <Tooltip labelFormatter={(d) => formatDate(String(d))} {...TOOLTIP_PROPS} />
          <Legend {...LEGEND_PROPS} />
          <ReferenceLine y={0} stroke={CHART.secondary} strokeOpacity={0.5} />
          <Area type="monotone" dataKey="tsb" name="Form (TSB)" fill={CHART.accentFill} stroke={CHART.accentStroke}
                fillOpacity={0.55} strokeWidth={1} isAnimationActive={false} />
          <Line type="monotone" dataKey="ctl" name="Fitness (CTL)" stroke={CHART.primary} strokeWidth={2.25}
                dot={false} isAnimationActive={false} />
          <Line type="monotone" dataKey="atl" name="Fatigue (ATL)" stroke={CHART.secondary} strokeWidth={1.5}
                strokeDasharray="5 3" dot={false} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
