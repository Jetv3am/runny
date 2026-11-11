"use client";

import type { RacePrediction } from "@/lib/api/client";
import { formatDuration } from "@/lib/format";
import { useFormat } from "@/lib/units";

/** One prediction as a cell; meant to sit inside a StatGroup-style divided strip. */
export function PredictionCard({ prediction, detailed = false }: {
  prediction: RacePrediction;
  detailed?: boolean;
}) {
  const f = useFormat();
  return (
    <article className="bg-surface px-5 py-4">
      <h3 className="text-[13px] text-ink-muted">{prediction.label}</h3>
      <p className="mt-1.5 text-[26px] font-medium tabular-nums tracking-[-0.02em] text-ink">
        {formatDuration(prediction.predicted_s)}
      </p>
      <p className="text-[13px] tabular-nums text-ink-muted">{f.pace(prediction.pace_s_per_km)}</p>
      {detailed && (
        <div className="mt-4">
          <RangeBar prediction={prediction} />
          <dl className="mt-2 flex justify-between text-[12px] tabular-nums text-ink-muted">
            <div><dt className="sr-only">Optimistic</dt><dd>{formatDuration(prediction.p10_s)}</dd></div>
            <div><dt className="sr-only">Conservative</dt><dd>{formatDuration(prediction.p90_s)}</dd></div>
          </dl>
        </div>
      )}
    </article>
  );
}

/** p10-p90 band with the estimate marked. Text equivalents render alongside. */
function RangeBar({ prediction }: { prediction: RacePrediction }) {
  const span = prediction.p90_s - prediction.p10_s;
  const position = span ? ((prediction.predicted_s - prediction.p10_s) / span) * 100 : 50;
  return (
    <div className="relative h-1.5 rounded-full bg-accent" aria-hidden="true">
      <span className="absolute top-1/2 h-3.5 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink"
            style={{ left: `${position}%` }} />
    </div>
  );
}

/** Divided strip of prediction cells (Ramp KPI style). */
export function PredictionStrip({ predictions, detailed = false }: {
  predictions: RacePrediction[];
  detailed?: boolean;
}) {
  return (
    <div className="grid grid-cols-2 gap-px overflow-hidden rounded-xl border border-line bg-line lg:grid-cols-4">
      {predictions.map((p) => <PredictionCard key={p.key} prediction={p} detailed={detailed} />)}
    </div>
  );
}
