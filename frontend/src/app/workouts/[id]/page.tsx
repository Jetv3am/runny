import type { Metadata } from "next";
import { Suspense } from "react";
import { Loading } from "@/components/ui";
import { WorkoutDetailView } from "./workout-detail-view";

export const metadata: Metadata = { title: "Workout" };

export default function WorkoutDetailPage() {
  // useParams() is request data under Cache Components; Suspense lets the shell prerender.
  return (
    <Suspense fallback={<Loading label="Loading workout" />}>
      <WorkoutDetailView />
    </Suspense>
  );
}
