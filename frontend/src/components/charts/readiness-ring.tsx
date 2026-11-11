import { Pill, type Tone } from "@/components/ui";

function toneFor(score: number): Tone {
  if (score >= 75) return "positive";
  if (score >= 50) return "warning";
  return "negative";
}

/** Readiness gauge. Monochrome arc; the status is carried by text + a tinted pill. */
export function ReadinessRing({ score, label }: { score: number; label: string }) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference * (1 - score / 100);

  return (
    <div className="flex items-center gap-5">
      <svg viewBox="0 0 100 100" className="size-24 shrink-0" role="img"
           aria-label={`Readiness ${score} out of 100: ${label}`}>
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--color-line)" strokeWidth="8" />
        <circle cx="50" cy="50" r={radius} fill="none" stroke="var(--color-ink)" strokeWidth="8"
                strokeLinecap="round" strokeDasharray={circumference} strokeDashoffset={offset}
                transform="rotate(-90 50 50)" />
        <text x="50" y="57" textAnchor="middle" className="fill-ink text-[26px] font-medium tracking-tight">
          {score}
        </text>
      </svg>
      <div>
        <p className="text-[13px] text-ink-muted">Readiness today</p>
        <p className="mt-0.5 text-[18px] font-medium tracking-[-0.01em] text-ink">{label}</p>
        <div className="mt-2"><Pill tone={toneFor(score)}>{score} / 100</Pill></div>
      </div>
    </div>
  );
}
