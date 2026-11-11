import type { Metadata } from "next";
import { PlanView } from "./plan-view";

export const metadata: Metadata = { title: "Training plan" };

export default function PlanPage() {
  return <PlanView />;
}
