"use client";

import {
  Activity,
  CalendarDays,
  Gauge,
  LayoutDashboard,
  Menu,
  MessageCircle,
  Timer,
  Trophy,
  Upload,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Suspense, useState } from "react";
import { useFitnessSummary, useHealth } from "@/lib/api/hooks";
import { UnitsToggle } from "@/components/units-toggle";

const NAV_GROUPS = [
  {
    label: "Training",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/workouts", label: "Workouts", icon: Activity },
      { href: "/plan", label: "Training plan", icon: CalendarDays },
    ],
  },
  {
    label: "Insights",
    items: [
      { href: "/fitness", label: "Fitness", icon: Gauge },
      { href: "/predictions", label: "Predictions", icon: Trophy },
      { href: "/paces", label: "Training paces", icon: Timer },
    ],
  },
  {
    label: "Tools",
    items: [
      { href: "/coach", label: "AI coach", icon: MessageCircle },
      { href: "/import", label: "Import data", icon: Upload },
    ],
  },
] as const;

function isActive(pathname: string | null, href: string) {
  if (pathname === null) return false;
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

type NavProps = { onNavigate?: () => void };

/** Pure list; `pathname` is null in the prerendered fallback (no active highlight yet). */
function NavList({ pathname, onNavigate }: NavProps & { pathname: string | null }) {
  return (
    <div className="space-y-6">
      {NAV_GROUPS.map((group) => (
        <div key={group.label}>
          <p className="mb-1.5 px-2.5 text-[12px] font-medium text-ink-muted">{group.label}</p>
          <ul className="space-y-0.5">
            {group.items.map(({ href, label, icon: Icon }) => {
              const active = isActive(pathname, href);
              return (
                <li key={href}>
                  <Link
                    href={href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={`flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[14px] transition-colors ${
                      active
                        ? "bg-surface font-medium text-ink shadow-hairline ring-1 ring-line"
                        : "text-ink-muted hover:bg-hover hover:text-ink"
                    }`}
                  >
                    <Icon aria-hidden className="size-4 shrink-0" strokeWidth={active ? 2.25 : 1.75} />
                    {label}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </div>
  );
}

function ActiveNavList({ onNavigate }: NavProps) {
  return <NavList pathname={usePathname()} onNavigate={onNavigate} />;
}

/** usePathname is request data under Cache Components, so it must sit inside Suspense. */
function NavLinks({ onNavigate }: NavProps) {
  return (
    <Suspense fallback={<NavList pathname={null} onNavigate={onNavigate} />}>
      <ActiveNavList onNavigate={onNavigate} />
    </Suspense>
  );
}

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5 px-2.5 text-[15px] font-semibold tracking-[-0.01em] text-ink">
      <span aria-hidden className="grid size-7 place-items-center rounded-lg bg-accent text-[12px] font-bold text-ink">
        RC
      </span>
      Running Coach
    </Link>
  );
}

function AthleteChip() {
  const { data: summary } = useFitnessSummary();
  const { data: health } = useHealth();
  const name = summary?.athlete_name ?? "Athlete";
  const initials = name.split(" ").map((part) => part[0]).join("").slice(0, 2);
  return (
    <div className="flex items-center gap-2.5 rounded-lg px-2.5 py-2">
      <span aria-hidden className="grid size-7 place-items-center rounded-full bg-ink text-[11px] font-semibold text-white">
        {initials}
      </span>
      <div className="min-w-0">
        <p className="truncate text-[13px] font-medium text-ink">{name}</p>
        <p className="truncate text-[12px] text-ink-muted">
          {health?.data_source === "demo" ? "Demo data" : "Apple Health"}
        </p>
      </div>
    </div>
  );
}

function SidebarFooter() {
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between px-2.5">
        <span className="text-[12px] text-ink-muted">Units</span>
        <UnitsToggle size="sm" />
      </div>
      <AthleteChip />
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="min-h-screen lg:flex">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-surface focus:px-4 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>

      <aside className="hidden w-60 shrink-0 flex-col gap-8 px-3 py-5 lg:sticky lg:top-0 lg:flex lg:h-screen">
        <Brand />
        <nav aria-label="Main" className="flex-1 overflow-y-auto">
          <NavLinks />
        </nav>
        <SidebarFooter />
      </aside>

      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-line bg-canvas/90 px-4 backdrop-blur lg:hidden">
        <Brand />
        <button
          type="button"
          onClick={() => setMenuOpen((open) => !open)}
          aria-expanded={menuOpen}
          aria-controls="mobile-nav"
          className="grid size-9 place-items-center rounded-lg text-ink hover:bg-hover"
        >
          {menuOpen ? <X aria-hidden className="size-5" /> : <Menu aria-hidden className="size-5" />}
          <span className="sr-only">{menuOpen ? "Close menu" : "Open menu"}</span>
        </button>
      </header>
      {menuOpen && (
        <nav id="mobile-nav" aria-label="Main" className="space-y-6 border-b border-line bg-canvas p-4 lg:hidden">
          <NavLinks onNavigate={() => setMenuOpen(false)} />
          <SidebarFooter />
        </nav>
      )}

      {/* Inset white panel - the signature "modern app" frame. */}
      <main id="main" className="min-w-0 flex-1 lg:py-2 lg:pr-2">
        <div className="min-h-full bg-surface px-4 py-6 sm:px-8 lg:min-h-[calc(100vh-1rem)] lg:rounded-xl lg:border lg:border-line lg:px-10 lg:py-9">
          <div className="mx-auto max-w-6xl">{children}</div>
        </div>
      </main>
    </div>
  );
}
