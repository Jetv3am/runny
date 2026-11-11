"use client";

import { useState } from "react";
import { WeeklyVolumeChart } from "@/components/charts/weekly-volume-chart";
import { SegmentedControl } from "@/components/segmented-control";
import { Button, Card, EmptyState, PageHeader, QueryState } from "@/components/ui";
import { WorkoutTable } from "@/components/workout-table";
import type { WorkoutType } from "@/lib/api/client";
import { useWeeklyVolume, useWorkouts } from "@/lib/api/hooks";
import { WORKOUT_TYPE_KEYS, WORKOUT_TYPES } from "@/lib/workout-types";

const PAGE_SIZE = 20;
type Filter = WorkoutType | "all";

const FILTERS = [
  { value: "all" as const, label: "All" },
  ...WORKOUT_TYPE_KEYS.map((key) => ({ value: key, label: WORKOUT_TYPES[key].label })),
];

export function WorkoutsView() {
  const [filter, setFilter] = useState<Filter>("all");
  const [page, setPage] = useState(0);
  const workouts = useWorkouts({
    limit: PAGE_SIZE,
    offset: page * PAGE_SIZE,
    type: filter === "all" ? undefined : filter,
  });
  const weekly = useWeeklyVolume(16);

  const chooseFilter = (next: Filter) => {
    setFilter(next);
    setPage(0);
  };

  return (
    <>
      <PageHeader title="Workouts" description="Every run imported from Apple Health." />

      <QueryState query={weekly}>{(data) => <WeeklyVolumeChart data={data} />}</QueryState>

      <Card
        className="mt-6"
        flush
        title="All runs"
        action={<SegmentedControl<Filter> label="Filter by workout type" options={FILTERS} value={filter}
                                         onChange={chooseFilter} size="sm" />}
      >
        <QueryState query={workouts}>
          {(data) => {
            if (data.items.length === 0) {
              return <div className="p-5"><EmptyState message="No workouts match this filter." /></div>;
            }
            const lastPage = Math.max(0, Math.ceil(data.total / PAGE_SIZE) - 1);
            return (
              <>
                <WorkoutTable workouts={data.items} caption="Workouts, newest first" />
                <nav aria-label="Pagination" className="flex items-center justify-between border-t border-line px-5 py-3">
                  <p className="text-[13px] tabular-nums text-ink-muted">
                    {data.offset + 1}–{data.offset + data.items.length} of {data.total}
                  </p>
                  <div className="flex gap-2">
                    <Button disabled={page === 0} onClick={() => setPage((p) => p - 1)}>Previous</Button>
                    <Button disabled={page >= lastPage} onClick={() => setPage((p) => p + 1)}>Next</Button>
                  </div>
                </nav>
              </>
            );
          }}
        </QueryState>
      </Card>
    </>
  );
}
