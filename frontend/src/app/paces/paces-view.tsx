"use client";

import { Card, EmptyState, PageHeader, QueryState } from "@/components/ui";
import { UnitsToggle } from "@/components/units-toggle";
import type { PaceZone } from "@/lib/api/client";
import { useTrainingPaces } from "@/lib/api/hooks";
import { useFormat } from "@/lib/units";

/** Intensity ramp: zones darken from easy to repetition, so order reads without hue. */
const ZONE_SHADE: Record<string, string> = {
  easy: "bg-accent ring-1 ring-inset ring-chart-accent-stroke/40",
  marathon: "bg-line-strong",
  threshold: "bg-chart-secondary",
  interval: "bg-ink/75",
  repetition: "bg-ink",
};

/** Bar positioned on a shared slow-to-fast scale. */
function ZoneBar({ zone, scale }: { zone: PaceZone; scale: { fastest: number; slowest: number } }) {
  const span = scale.slowest - scale.fastest;
  const left = ((scale.slowest - zone.slow_s_per_km) / span) * 100;
  const width = Math.max(((zone.slow_s_per_km - zone.fast_s_per_km) / span) * 100, 2);
  return (
    <div className="relative h-2 rounded-full bg-hover" aria-hidden="true">
      <span className={`absolute inset-y-0 rounded-full ${ZONE_SHADE[zone.key] ?? "bg-ink"}`}
            style={{ left: `${left}%`, width: `${width}%` }} />
    </div>
  );
}

export function PacesView() {
  const paces = useTrainingPaces();
  const f = useFormat();

  return (
    <>
      <PageHeader
        title="Training paces"
        description="Run each session at the right effort. Paces update as your fitness changes."
        actions={<UnitsToggle />}
      />
      <QueryState
        query={paces}
        empty={<EmptyState message="Log a race effort to unlock personalised paces." href="/import" cta="Import data" />}
      >
        {(p) => {
          const scale = {
            fastest: Math.min(...p.zones.map((z) => z.fast_s_per_km)) - 10,
            slowest: Math.max(...p.zones.map((z) => z.slow_s_per_km)) + 10,
          };
          return (
            <Card title={`Your zones · VDOT ${p.vdot}`} flush>
              <ul>
                {p.zones.map((zone) => (
                  <li key={zone.key}
                      className="grid gap-3 border-b border-line px-5 py-4 last:border-0 md:grid-cols-[200px_1fr_180px] md:items-center md:gap-8">
                    <div>
                      <h3 className="font-medium text-ink">{zone.name}</h3>
                      <p className="text-[13px] text-ink-muted">{zone.purpose}</p>
                    </div>
                    <ZoneBar zone={zone} scale={scale} />
                    <p className="text-[18px] font-medium tabular-nums tracking-[-0.01em] text-ink md:text-right">
                      {f.paceRange(zone.fast_s_per_km, zone.slow_s_per_km)}
                    </p>
                  </li>
                ))}
              </ul>
              <p className="flex justify-between border-t border-line px-5 py-2.5 text-[12px] text-ink-muted" aria-hidden="true">
                <span>← Slower</span><span>Faster →</span>
              </p>
            </Card>
          );
        }}
      </QueryState>
    </>
  );
}
