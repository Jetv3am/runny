"use client";

import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { WorkoutDetail } from "@/lib/api/client";
import { useFormat } from "@/lib/units";
import { AXIS_PROPS, CHART, ChartFrame, LEGEND_PROPS, TOOLTIP_PROPS } from "./chart-frame";

export function SplitsChart({ workout }: { workout: WorkoutDetail }) {
  const f = useFormat();
  // Plot raw s/km; only the tick/tooltip labels are converted to the user's units.
  const splits = workout.splits.map((s) => ({ ...s, label: String(s.index) }));
  const fastest = workout.splits.reduce((a, b) => (b.pace_s_per_km < a.pace_s_per_km ? b : a),
                                        workout.splits[0]);
  const summary = fastest
    ? `${splits.length} splits. Fastest was split ${fastest.index} at ${f.pace(fastest.pace_s_per_km)}.`
    : "No split data for this workout.";
  // Watch distance samples carry no elevation: skip the column rather than show dashes.
  const hasElevation = workout.splits.some((s) => s.elevation_delta_m != null);
  const signed = (m: number) => `${m > 0 ? "+" : ""}${m} m`;

  return (
    <ChartFrame
      title="Splits"
      summary={summary}
      table={{
        columns: ["Split", "Distance", "Pace", "Avg HR", ...(hasElevation ? ["Elevation"] : [])],
        rows: workout.splits.map((s) => [
          s.index, f.distance(s.distance_m, 2), f.pace(s.pace_s_per_km), s.avg_hr ?? "–",
          ...(hasElevation ? [s.elevation_delta_m != null ? signed(s.elevation_delta_m) : "–"] : []),
        ]),
      }}
    >
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={splits} margin={{ top: 8, right: 0, bottom: 0, left: -4 }}>
          <CartesianGrid stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="label" {...AXIS_PROPS} />
          <YAxis yAxisId="pace" reversed domain={["dataMin - 15", "dataMax + 15"]}
                 tickFormatter={(v: number) => f.paceShort(v)}
                 width={52} {...AXIS_PROPS} />
          <YAxis yAxisId="hr" orientation="right" domain={["dataMin - 10", "dataMax + 5"]} width={40}
                 {...AXIS_PROPS} />
          <Tooltip
            labelFormatter={(l) => `Split ${l}`}
            formatter={(value, name) =>
              name === "Pace"
                ? [f.paceShort(Number(value)), name]
                : [`${value} bpm`, name]}
            {...TOOLTIP_PROPS}
          />
          <Legend {...LEGEND_PROPS} />
          {/* Pace axis is reversed (up = faster), so pace must be a line: bars would hang from the top. */}
          <Line yAxisId="pace" dataKey="pace_s_per_km" name="Pace" stroke={CHART.primary} strokeWidth={2.5}
                dot={{ r: 3 }} isAnimationActive={false} />
          <Line yAxisId="hr" dataKey="avg_hr" name="Heart rate" stroke={CHART.negative} strokeWidth={1.5}
                strokeDasharray="5 3" dot={{ r: 2 }} isAnimationActive={false} />
        </ComposedChart>
      </ResponsiveContainer>
    </ChartFrame>
  );
}
