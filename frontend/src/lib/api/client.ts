import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

/** Same-origin client: Next.js rewrites /api/* to the FastAPI backend. */
export const api = createClient<paths>({ baseUrl: "" });

type Schemas = components["schemas"];
export type FitnessSummary = Schemas["FitnessSummary"];
export type DailyMetric = Schemas["DailyMetric"];
export type HealthMetric = Schemas["HealthMetric"];
export type WorkoutSummary = Schemas["WorkoutSummary"];
export type WorkoutDetail = Schemas["WorkoutDetail"];
export type WorkoutPage = Schemas["WorkoutPage"];
export type WorkoutType = Schemas["WorkoutType"];
export type WeeklyVolume = Schemas["WeeklyVolume"];
export type TrainingPaces = Schemas["TrainingPaces"];
export type PaceZone = Schemas["PaceZoneOut"];
export type RacePredictions = Schemas["RacePredictions"];
export type RacePrediction = Schemas["RacePrediction"];
export type TrainingPlan = Schemas["TrainingPlan"];
export type PlanWeek = Schemas["PlanWeekOut"];
export type PlannedSession = Schemas["PlannedSessionOut"];
export type ImportRecord = Schemas["ImportRecord"];
export type ChatMessage = Schemas["ChatMessage"];

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
  }
}

type FetchResult<T> = { data?: T; error?: unknown; response: Response };

function errorDetail(error: unknown): string | undefined {
  if (error && typeof error === "object" && "detail" in error) {
    const detail = (error as { detail: unknown }).detail;
    return typeof detail === "string" ? detail : undefined;
  }
  return undefined;
}

/** Turn openapi-fetch's {data, error} into a value or a thrown ApiError (what React Query wants). */
export async function unwrap<T>(request: Promise<FetchResult<T>>): Promise<T> {
  const { data, error, response } = await request;
  if (error !== undefined || data === undefined) {
    throw new ApiError(response.status, errorDetail(error) ?? `Request failed (${response.status})`);
  }
  return data;
}

/** For resources that legitimately may not exist yet (cold start): 404 becomes null. */
export async function unwrapOptional<T>(request: Promise<FetchResult<T>>): Promise<T | null> {
  try {
    return await unwrap(request);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null;
    throw err;
  }
}
