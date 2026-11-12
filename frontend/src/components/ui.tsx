import Link from "next/link";
import { AlertTriangle, ArrowDownRight, ArrowUpRight, Loader2 } from "lucide-react";
import type { WorkoutType } from "@/lib/api/client";
import { WORKOUT_TYPES } from "@/lib/workout-types";

/* ---------- Layout ---------------------------------------------------------- */

/** Cell styles for dense, hairline-divided tables that sit inside a `flush` Card. */
export const TABLE_HEAD = "px-5 py-2.5 text-[12px] font-medium text-ink-muted";
export const TABLE_CELL = "px-5 py-3";

export function PageHeader({ title, description, actions, eyebrow }: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
  eyebrow?: React.ReactNode;
}) {
  return (
    <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
      <div>
        {eyebrow && <div className="mb-2 text-[13px] text-ink-muted">{eyebrow}</div>}
        <h1 className="text-[28px] font-medium leading-tight tracking-[-0.02em] text-ink">{title}</h1>
        {description && <p className="mt-1.5 text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function Card({ title, action, children, className = "", flush = false }: {
  title?: React.ReactNode;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  /** No body padding (for edge-to-edge tables/lists). */
  flush?: boolean;
}) {
  return (
    <section className={`rounded-xl border border-line bg-surface ${className}`}>
      {(title || action) && (
        <div className="flex min-h-12 items-center justify-between gap-3 border-b border-line px-5 py-3">
          {title && <h2 className="text-[14px] font-medium text-ink">{title}</h2>}
          {action}
        </div>
      )}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

/** Ramp-style KPI strip: one bordered container divided into cells. Children are <Stat>s. */
export function StatGroup({ children, columns = 4 }: { children: React.ReactNode; columns?: 2 | 3 | 4 }) {
  // 2-up even on phones (Ramp mobile style): four stacked KPIs would eat a whole screen.
  const cols = { 2: "grid-cols-2", 3: "grid-cols-1 sm:grid-cols-3", 4: "grid-cols-2 lg:grid-cols-4" }[columns];
  return (
    <dl className={`grid gap-px overflow-hidden rounded-xl border border-line bg-line ${cols}`}>
      {children}
    </dl>
  );
}

export function Stat({ label, value, hint, delta }: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  delta?: React.ReactNode;
}) {
  return (
    <div className="bg-surface px-5 py-4">
      <dt className="text-[13px] text-ink-muted">{label}</dt>
      <dd className="mt-1.5 flex flex-wrap items-baseline gap-2">
        <span className="text-[26px] font-medium tabular-nums tracking-[-0.02em] text-ink">{value}</span>
        {delta}
      </dd>
      {hint && <dd className="mt-0.5 text-[13px] text-ink-muted">{hint}</dd>}
    </div>
  );
}

/* ---------- Pills & badges -------------------------------------------------- */

const TONES = {
  positive: "bg-positive-soft text-positive",
  negative: "bg-negative-soft text-negative",
  warning: "bg-warning-soft text-warning",
  info: "bg-info-soft text-info",
  neutral: "bg-hover text-ink-muted",
  accent: "bg-accent text-ink",
} as const;
export type Tone = keyof typeof TONES;

export function Pill({ tone = "neutral", children }: { tone?: Tone; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-[12px] font-medium ${TONES[tone]}`}>
      {children}
    </span>
  );
}

/** Change indicator: arrow + signed text, so direction never relies on colour alone. */
export function Delta({ value, suffix = "", goodWhenPositive = true }: {
  value: number;
  suffix?: string;
  goodWhenPositive?: boolean;
}) {
  const up = value >= 0;
  const Icon = up ? ArrowUpRight : ArrowDownRight;
  const tone: Tone = value === 0 ? "neutral" : up === goodWhenPositive ? "positive" : "negative";
  return (
    <Pill tone={tone}>
      <Icon aria-hidden className="size-3" />
      {up ? "+" : ""}{value}{suffix}
    </Pill>
  );
}

export function TypeBadge({ type }: { type: WorkoutType }) {
  const { label, color } = WORKOUT_TYPES[type];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border border-line bg-surface px-2 py-0.5 text-[12px] font-medium text-ink">
      <span aria-hidden className="size-1.5 rounded-full" style={{ backgroundColor: color }} />
      {label}
    </span>
  );
}

/* ---------- Buttons & links ------------------------------------------------- */

const BUTTON = {
  primary: "bg-ink text-white hover:bg-ink/85",
  secondary: "border border-line bg-surface text-ink hover:bg-hover",
  ghost: "text-ink hover:bg-hover",
} as const;
const BUTTON_BASE =
  "inline-flex h-9 items-center justify-center gap-1.5 rounded-lg px-3 text-[14px] font-medium transition-colors disabled:pointer-events-none disabled:opacity-50";

export function ButtonLink({ href, variant = "secondary", children }: {
  href: string;
  variant?: keyof typeof BUTTON;
  children: React.ReactNode;
}) {
  return <Link href={href} className={`${BUTTON_BASE} ${BUTTON[variant]}`}>{children}</Link>;
}

export function Button({ variant = "secondary", className = "", ...props }:
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: keyof typeof BUTTON }) {
  return <button type="button" className={`${BUTTON_BASE} ${BUTTON[variant]} ${className}`} {...props} />;
}

export function TextLink({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className="text-[13px] font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
      {children}
    </Link>
  );
}

/* ---------- Query states ---------------------------------------------------- */

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 py-8 text-ink-muted">
      <Loader2 aria-hidden className="size-4 animate-spin" />
      {label}…
    </div>
  );
}

export function ErrorState({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : "Something went wrong.";
  return (
    <div role="alert" className="flex items-start gap-2 rounded-xl border border-negative/20 bg-negative-soft p-4 text-negative">
      <AlertTriangle aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div>
        <p className="font-medium">Couldn&apos;t load this data</p>
        <p className="text-[13px]">{message} Is the API running? Try <code>make dev</code>.</p>
      </div>
    </div>
  );
}

export function EmptyState({ message, href, cta }: { message: string; href?: string; cta?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-line-strong p-8 text-center text-ink-muted">
      <p>{message}</p>
      {href && cta && <div className="mt-3"><ButtonLink href={href}>{cta}</ButtonLink></div>}
    </div>
  );
}

/** Renders loading/error/empty states so pages only handle the happy path. */
export function QueryState<T>({ query, children, empty }: {
  query: { data: T | null | undefined; isPending: boolean; error: unknown };
  children: (data: T) => React.ReactNode;
  empty?: React.ReactNode;
}) {
  if (query.isPending) return <Loading />;
  if (query.error) return <ErrorState error={query.error} />;
  if (query.data == null) {
    return <>{empty ?? <EmptyState message="Not enough data yet." href="/import" cta="Import your runs" />}</>;
  }
  return <>{children(query.data)}</>;
}
