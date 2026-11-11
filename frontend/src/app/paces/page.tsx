import type { Metadata } from "next";
import { PacesView } from "./paces-view";

export const metadata: Metadata = { title: "Training paces" };

export default function PacesPage() {
  return <PacesView />;
}
