import type { Metadata } from "next";
import { ImportView } from "./import-view";

export const metadata: Metadata = { title: "Import data" };

export default function ImportPage() {
  return <ImportView />;
}
