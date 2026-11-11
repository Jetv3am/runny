"use client";

import { useId, useState } from "react";

export type DataTable = {
  columns: string[];
  rows: (string | number)[][];
};

/** Series colours resolve to the design tokens in globals.css - no hex values in chart code. */
export const CHART = {
  primary: "var(--color-chart-primary)",
  secondary: "var(--color-chart-secondary)",
  accentFill: "var(--color-chart-accent-fill)",
  accentStroke: "var(--color-chart-accent-stroke)",
  grid: "var(--color-chart-grid)",
  negative: "var(--color-negative)",
} as const;

export const AXIS_PROPS = {
  stroke: "var(--color-ink-muted)",
  fontSize: 12,
  tickLine: false,
  axisLine: false,
} as const;

/** Dark, compact tooltip (Ramp style). */
export const TOOLTIP_PROPS = {
  contentStyle: {
    background: "var(--color-ink)",
    border: "none",
    borderRadius: 8,
    fontSize: 12,
    padding: "8px 10px",
    boxShadow: "0 8px 24px rgb(0 0 0 / 0.18)",
  },
  labelStyle: { color: "#fff", fontWeight: 500, marginBottom: 4 },
  itemStyle: { color: "#fff", padding: 0 },
  cursor: { stroke: "var(--color-line-strong)", strokeWidth: 1 },
} as const;

export const LEGEND_PROPS = {
  iconSize: 8,
  wrapperStyle: { fontSize: 12, color: "var(--color-ink-muted)", paddingTop: 8 },
} as const;

/**
 * Accessible chart card: heading, plain-language summary, fixed-height plot,
 * and a toggleable data table so information never depends on visuals alone.
 */
export function ChartFrame({ title, summary, table, height = 280, children, action }: {
  title: string;
  summary: string;
  table: DataTable;
  height?: number;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const summaryId = useId();

  return (
    <figure className="flex h-full flex-col rounded-xl border border-line bg-surface" aria-describedby={summaryId}>
      <div className="flex flex-wrap items-start justify-between gap-3 px-5 pt-4">
        <div className="min-w-0">
          <h2 className="text-[14px] font-medium text-ink">{title}</h2>
          <figcaption id={summaryId} className="mt-0.5 text-[13px] text-ink-muted">{summary}</figcaption>
        </div>
        <div className="flex items-center gap-2">
          {action}
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-expanded={showTable}
            aria-controls={tableId}
            className="h-8 rounded-lg px-2.5 text-[13px] font-medium text-ink-muted hover:bg-hover hover:text-ink"
          >
            {showTable ? "Hide table" : "Table"}
          </button>
        </div>
      </div>
      {/* Grows to fill the card when a grid row is taller than the chart (no dead space).
          The absolute layer gives Recharts a definite size in both stretched and plain layouts;
          a bare `height: 100%` resolves to 0 when the parent's height is only a min-height. */}
      <div className="relative flex-1" style={{ minHeight: height + 28 }} aria-hidden="true">
        <div className="absolute inset-0 px-3 pb-4 pt-3">{children}</div>
      </div>
      <div id={tableId} hidden={!showTable} className="max-h-72 overflow-auto border-t border-line">
        <table className="w-full text-left text-[13px]">
          <caption className="sr-only">{title} data</caption>
          <thead className="sticky top-0 bg-surface text-ink-muted">
            <tr className="border-b border-line">
              {table.columns.map((c) => (
                <th key={c} scope="col" className="px-5 py-2 font-medium">{c}</th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {table.rows.map((row, i) => (
              <tr key={i} className="border-b border-line last:border-0">
                {row.map((cell, j) => (
                  <td key={j} className="px-5 py-2 text-ink">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
