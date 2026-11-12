"use client";

import { Loader2, RefreshCw } from "lucide-react";
import { Button, ButtonLink, Card, Pill, QueryState, Stat, StatGroup, type Tone } from "@/components/ui";
import type { ModelCard as Model } from "@/lib/api/client";
import { useRaceModel, useRetrainRaceModel } from "@/lib/api/hooks";
import { formatDate, formatDuration } from "@/lib/format";

const ALGORITHMS: Record<string, string> = { ridge: "Linear (ridge)", gbm: "Gradient-boosted trees" };

const STATUS: Record<Model["status"], { label: string; tone: Tone }> = {
  active: { label: "In use", tone: "positive" },
  baseline_better: { label: "VDOT in use", tone: "neutral" },
  collecting_data: { label: "Collecting data", tone: "info" },
  not_trained: { label: "Not trained", tone: "neutral" },
  demo: { label: "Demo data", tone: "neutral" },
};

const percent = (value: number) => `${value.toFixed(1)}%`;

/** Why predictions do (or don't) use the personal ML model, with its test scores. */
export function ModelCard({ className = "" }: { className?: string }) {
  const model = useRaceModel();
  const retrain = useRetrainRaceModel();
  const status = model.data?.status;
  return (
    <Card
      className={className}
      title={
        <span className="flex items-center gap-2">
          Prediction model {status && <Pill tone={STATUS[status].tone}>{STATUS[status].label}</Pill>}
        </span>
      }
      action={status && status !== "demo" && (
        <Button onClick={() => retrain.mutate()} disabled={retrain.isPending}>
          {retrain.isPending
            ? <Loader2 aria-hidden className="size-4 animate-spin" />
            : <RefreshCw aria-hidden className="size-4" />}
          {retrain.isPending ? "Training…" : "Retrain"}
        </Button>
      )}
    >
      <QueryState query={model}>{(card) => <ModelBody card={card} />}</QueryState>
      <p aria-live="polite" className="mt-3 text-[13px] text-ink-muted empty:hidden">
        {retrain.isSuccess && !retrain.isPending ? "Retrained on your latest data." : ""}
      </p>
      {retrain.error && (
        <p role="alert" className="mt-3 text-[13px] text-negative">{retrain.error.message}</p>
      )}
    </Card>
  );
}

function ModelBody({ card }: { card: Model }) {
  switch (card.status) {
    case "demo":
      return (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-ink-muted">The model trains on your own runs, so there&apos;s nothing to learn from demo data.</p>
          <ButtonLink href="/import">Import your runs</ButtonLink>
        </div>
      );
    case "not_trained":
      return <p className="text-ink-muted">Not trained yet. Retrain to build a model from your imported runs.</p>;
    case "collecting_data":
      return <Collecting card={card} />;
    default:
      return <Scores card={card} />;
  }
}

function Collecting({ card }: { card: Model }) {
  const share = Math.min(card.efforts / card.efforts_needed, 1);
  return (
    <>
      <div className="flex items-baseline justify-between text-[13px]">
        <span id="efforts-label" className="text-ink">Race-quality efforts</span>
        <span className="tabular-nums text-ink-muted">{card.efforts} of {card.efforts_needed}</span>
      </div>
      <div role="progressbar" aria-labelledby="efforts-label" aria-valuemin={0}
           aria-valuemax={card.efforts_needed} aria-valuenow={card.efforts}
           className="mt-2 h-2 overflow-hidden rounded-full bg-hover">
        <div className="h-full rounded-full bg-ink" style={{ width: `${share * 100}%` }} />
      </div>
      <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
        Races count, and so do hard runs recorded with heart rate at race level. Until there are
        enough to test a model fairly, predictions use VDOT.
      </p>
    </>
  );
}

function Scores({ card }: { card: Model }) {
  const { ml, baseline } = card;
  if (!ml || !baseline) return null;
  const inUse = card.status === "active";
  return (
    <>
      <StatGroup columns={4}>
        <Stat label="ML error" value={percent(ml.mape_pct)} hint={`avg ${formatDuration(ml.mae_s)} off`} />
        <Stat label="VDOT error" value={percent(baseline.mape_pct)} hint={`avg ${formatDuration(baseline.mae_s)} off`} />
        <Stat label="Range hit rate" value={card.band_coverage_pct != null ? percent(card.band_coverage_pct) : "–"}
              hint="Aim: about 80%" />
        <Stat label="Tested on" value={card.test_efforts ?? "–"}
              hint={`unseen efforts · ${ALGORITHMS[card.algorithm ?? ""] ?? card.algorithm}`} />
      </StatGroup>
      <p className="mt-3 text-[13px] leading-relaxed text-ink-muted">
        {inUse
          ? "The personal model beat VDOT on efforts it had never seen, so your predictions use it."
          : "The personal model wasn't clearly more accurate than VDOT, so your predictions stay on VDOT. It retrains after every import."}
        {" "}Error is the average gap between predicted and actual times, scored walk-forward: always
        on efforts from after the data it learned from.
        {card.trained_at && ` Trained ${formatDate(card.trained_at, { month: "short", day: "numeric", year: "numeric" })}.`}
      </p>
    </>
  );
}
