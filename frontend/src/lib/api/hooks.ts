"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api, unwrap, unwrapOptional, type ImportRecord, type WorkoutType } from "./client";


export function useHealth() {
  return useQuery({ queryKey: ["health"], queryFn: () => unwrap(api.GET("/api/v1/health")) });
}

export function useFitnessSummary() {
  return useQuery({
    queryKey: ["fitness", "summary"],
    queryFn: () => unwrap(api.GET("/api/v1/fitness/summary")),
  });
}

export function useTrainingPaces() {
  return useQuery({
    queryKey: ["fitness", "paces"],
    queryFn: () => unwrapOptional(api.GET("/api/v1/fitness/paces")),
  });
}

export function useDailyMetrics(days: number) {
  return useQuery({
    queryKey: ["metrics", "daily", days],
    queryFn: () => unwrap(api.GET("/api/v1/metrics/daily", { params: { query: { days } } })),
  });
}

export function useHealthMetrics(type: "vo2max" | "resting_hr") {
  return useQuery({
    queryKey: ["metrics", "health", type],
    queryFn: () => unwrap(api.GET("/api/v1/metrics/health", { params: { query: { type } } })),
  });
}

export function useWorkouts(params: { limit: number; offset: number; type?: WorkoutType }) {
  return useQuery({
    queryKey: ["workouts", params],
    queryFn: () => unwrap(api.GET("/api/v1/workouts", { params: { query: params } })),
    placeholderData: (previous) => previous,
  });
}

export function useWorkout(id: string) {
  return useQuery({
    queryKey: ["workouts", "detail", id],
    queryFn: () =>
      unwrap(api.GET("/api/v1/workouts/{workout_id}", { params: { path: { workout_id: id } } })),
  });
}

export function useWeeklyVolume(weeks: number) {
  return useQuery({
    queryKey: ["workouts", "weekly", weeks],
    queryFn: () => unwrap(api.GET("/api/v1/workouts/weekly", { params: { query: { weeks } } })),
  });
}

export function useRacePredictions() {
  return useQuery({
    queryKey: ["predictions", "race"],
    queryFn: () => unwrapOptional(api.GET("/api/v1/predictions/race")),
  });
}

export function usePersonalBests() {
  return useQuery({
    queryKey: ["fitness", "personal-bests"],
    queryFn: () => unwrap(api.GET("/api/v1/fitness/personal-bests")),
  });
}

const RACE_MODEL_KEY = ["models", "race-time"];

export function useRaceModel() {
  return useQuery({
    queryKey: RACE_MODEL_KEY,
    queryFn: () => unwrap(api.GET("/api/v1/models/race-time")),
  });
}

/** Retrain now. Predictions and the goal race may switch model, so both refresh. */
export function useRetrainRaceModel() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/models/race-time/train")),
    onSuccess: (card) => {
      queryClient.setQueryData(RACE_MODEL_KEY, card);
      void queryClient.invalidateQueries({ queryKey: ["predictions"] });
      void queryClient.invalidateQueries({ queryKey: ["plans"] });
    },
  });
}

export function useCurrentPlan() {
  return useQuery({
    queryKey: ["plans", "current"],
    queryFn: () => unwrap(api.GET("/api/v1/plans/current")),
  });
}

const IMPORT_POLL_MS = 1500;
const hasRunningImport = (records?: ImportRecord[]) =>
  records?.some((r) => r.status === "processing") ?? false;

/** Import history. Polls only while an import is running; when one finishes, refreshes
 *  every query, since the whole dashboard may have switched from demo to real data. */
export function useImports() {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["imports"],
    queryFn: () => unwrap(api.GET("/api/v1/imports")),
    refetchInterval: (q) => (hasRunningImport(q.state.data) ? IMPORT_POLL_MS : false),
  });
  const running = hasRunningImport(query.data);
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) void queryClient.invalidateQueries();
    wasRunning.current = running;
  }, [running, queryClient]);
  return query;
}
