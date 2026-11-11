"use client";

import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { HealthMetric } from "@/lib/api/client";
import { formatDate, formatSigned } from "@/lib/format";
import { AXIS_PROPS, CHART, ChartFrame, TOOLTIP_PROPS } from "./chart-frame";

export function HealthTrendChart({ title, data, higherIsBetter }: {
  title: string;
  data: HealthMetric[];
  higherIsBetter: boolean;
}) {
  const first = data[0];
  const last = data.at(-1);
  const unit = last?.unit ?? "";
  const summary = first && last
    ? `${first.value} → ${last.value} ${unit} (${formatSigned(last.value - first.value, 1)}), ` +
      `${(last.value > first.value) === higherIsBetter ? "an improvement" : "a decline"}.`
    : `No ${title.toLowerCase()} readings yet.`;

  return (
    <ChartFrame
      title={title}
      summary={summary}
      height={180}
      table={{
        columns: ["Date", `${title} (${unit})`],
        rows: [...data].reverse().map((d) => [formatDate(d.date), d.value]),
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -12 }}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="date" tickFormatter={(d: string) => formatDate(d)} minTickGap={32} {...AXIS_PROPS} />
          <YAxis domain={["dataMin - 2", "dataMax + 2"]} allowDecimals={false} {...AXIS_PROPS} />
          <Tooltip labelFormatter={(d) => formatDate(String(d))} formatter={(v) => [`${v} ${unit}`, title]}
                   {...TOOLTIP_PROPS} />
          <Area type="monotone" dataKey="value" stroke={CHART.primary} strokeWidth={2}
                fill={CHART.accentFill} fillOpacity={0.35} dot={false} isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
