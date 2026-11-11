import type { Metadata } from "next";
import { WorkoutsView } from "./workouts-view";

export const metadata: Metadata = { title: "Workouts" };

export default function WorkoutsPage() {
  return <WorkoutsView />;
}
