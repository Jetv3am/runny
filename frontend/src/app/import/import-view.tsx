"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, FileArchive, Loader2, UploadCloud } from "lucide-react";
import { useId, useRef, useState } from "react";
import { Card, EmptyState, PageHeader, Pill, QueryState, TextLink } from "@/components/ui";
import type { ImportRecord } from "@/lib/api/client";
import { useImports } from "@/lib/api/hooks";
import { API_ORIGIN } from "@/lib/api/origin";
import { formatBytes, formatDate } from "@/lib/format";

const ACCEPT = ".zip,.xml";
// Direct to FastAPI (CORS-enabled): the Next.js rewrite proxy can't stream multi-GB bodies.
const UPLOAD_URL = `${API_ORIGIN}/api/v1/imports`;

type UploadState =
  | { kind: "idle" }
  | { kind: "uploading"; progress: number; file: File }
  | { kind: "done"; record: ImportRecord }
  | { kind: "error"; message: string };

/** XHR (not fetch) because only XHR reports upload progress. */
function uploadWithProgress(file: File, onProgress: (pct: number) => void): Promise<ImportRecord> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    const body = new FormData();
    body.append("file", file);
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onload = () => {
      const json = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300) resolve(json as ImportRecord);
      else reject(new Error(typeof json.detail === "string" ? json.detail : `Upload failed (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error("Network error. Is the API running?"));
    xhr.open("POST", UPLOAD_URL);
    xhr.send(body);
  });
}

const STEPS = [
  "Open the Health app on your iPhone.",
  "Tap your profile picture, top right.",
  "Tap “Export All Health Data” and confirm.",
  "AirDrop export.zip to this computer and drop it here.",
];

const TH = "px-5 py-2.5 text-[12px] font-medium text-ink-muted";

/** Feedback for the file just uploaded: importing -> complete (with a way out) or failed. */
function JobBanner({ job }: { job: ImportRecord }) {
  if (job.status === "failed") {
    return (
      <p role="alert" className="rounded-xl bg-negative-soft p-4 text-[13px] text-negative">
        <span className="font-medium">{job.filename} couldn&apos;t be imported.</span> {job.message}
      </p>
    );
  }
  const done = job.status === "completed";
  return (
    <div className={`flex items-start gap-2 rounded-xl p-4 text-[13px] text-ink ${done ? "bg-positive-soft" : "bg-info-soft"}`}>
      {done
        ? <CheckCircle2 aria-hidden className="mt-0.5 size-4 shrink-0 text-positive" />
        : <Loader2 aria-hidden className="mt-0.5 size-4 shrink-0 animate-spin text-info" />}
      <div>
        <p className="font-medium">
          {done ? "Import complete" : `${job.filename} uploaded · ${formatBytes(job.size_bytes)}`}
        </p>
        <p className="text-ink-muted">
          {done ? job.message : `Importing… ${Math.round(job.progress)}%. The dashboard updates when it’s done.`}
        </p>
        {done && <div className="mt-2"><TextLink href="/">Go to your dashboard</TextLink></div>}
      </div>
    </div>
  );
}

function ImportStatus({ record }: { record: ImportRecord }) {
  if (record.status === "processing") {
    return (
      <Pill tone="info">
        <Loader2 aria-hidden className="size-3 animate-spin" /> Importing {Math.round(record.progress)}%
      </Pill>
    );
  }
  return record.status === "completed"
    ? <Pill tone="positive">Completed</Pill>
    : <Pill tone="negative">Failed</Pill>;
}

export function ImportView() {
  const [state, setState] = useState<UploadState>({ kind: "idle" });
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();
  const queryClient = useQueryClient();
  const history = useImports();

  const upload = async (file: File | undefined) => {
    if (!file) return;
    setState({ kind: "uploading", progress: 0, file });
    try {
      const record = await uploadWithProgress(file, (progress) =>
        setState({ kind: "uploading", progress, file }));
      setState({ kind: "done", record });
      await queryClient.invalidateQueries({ queryKey: ["imports"] });
    } catch (err) {
      setState({ kind: "error", message: (err as Error).message });
    } finally {
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  return (
    <>
      <PageHeader title="Import data" description="Bring in your runs from Apple Health." />

      <div className="grid gap-4 lg:grid-cols-[1fr_1.5fr]">
        <Card title="Export from your iPhone">
          <ol className="space-y-3">
            {STEPS.map((step, i) => (
              <li key={step} className="flex gap-3 text-ink">
                <span aria-hidden className="grid size-6 shrink-0 place-items-center rounded-md bg-hover text-[12px] font-medium">
                  {i + 1}
                </span>
                <span className="pt-0.5">{step}</span>
              </li>
            ))}
          </ol>
          <p className="mt-5 border-t border-line pt-4 text-[13px] text-ink-muted">
            Your data stays on this machine. Only runs and daily health readings are kept; the
            uploaded file is deleted once it has been read. Re-importing a newer export is safe:
            runs you already have are not duplicated.
          </p>
        </Card>

        <div>
          <label
            htmlFor={inputId}
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => { e.preventDefault(); setDragging(false); void upload(e.dataTransfer.files[0]); }}
            className={`flex h-full min-h-60 cursor-pointer flex-col items-center justify-center gap-3 rounded-xl border border-dashed p-10 text-center transition-colors has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-ink ${
              dragging ? "border-ink bg-accent-soft" : "border-line-strong hover:bg-hover"
            }`}
          >
            <span aria-hidden className="grid size-11 place-items-center rounded-xl bg-accent">
              <UploadCloud className="size-5 text-ink" />
            </span>
            <span className="font-medium text-ink">Drop export.zip here, or click to browse</span>
            <span className="text-[13px] text-ink-muted">.zip or .xml · up to 4 GB</span>
            <input id={inputId} ref={inputRef} type="file" accept={ACCEPT} className="sr-only"
                   disabled={state.kind === "uploading"}
                   onChange={(e) => void upload(e.target.files?.[0])} />
          </label>
        </div>
      </div>

      <div aria-live="polite" className="mt-4 empty:hidden">
        {state.kind === "uploading" && (
          <div className="rounded-xl border border-line p-4">
            <p className="mb-2 flex items-center gap-2 text-[13px] font-medium text-ink">
              <FileArchive aria-hidden className="size-4" /> Uploading {state.file.name}… {state.progress}%
            </p>
            <progress value={state.progress} max={100} className="h-1.5 w-full accent-ink"
                      aria-label={`Upload progress ${state.progress}%`} />
          </div>
        )}
        {state.kind === "done" && (
          // Follow the live job (polled history), not the stale upload response.
          <JobBanner job={history.data?.find((r) => r.id === state.record.id) ?? state.record} />
        )}
        {state.kind === "error" && (
          <p role="alert" className="rounded-xl bg-negative-soft p-4 text-[13px] text-negative">{state.message}</p>
        )}
      </div>

      <Card title="Import history" className="mt-8" flush>
        <QueryState query={history}>
          {(records) => records.length === 0 ? (
            <div className="p-5"><EmptyState message="No imports yet." /></div>
          ) : (
            <table className="w-full text-left">
              <caption className="sr-only">Previous imports</caption>
              <thead>
                <tr className="border-b border-line">
                  <th scope="col" className={TH}>When</th>
                  <th scope="col" className={TH}>File</th>
                  <th scope="col" className={`${TH} text-right`}>Size</th>
                  <th scope="col" className={`${TH} text-right`}>Status</th>
                </tr>
              </thead>
              <tbody>
                {records.map((r) => (
                  <tr key={r.id} className="border-b border-line last:border-0">
                    <td className="px-5 py-3 text-ink-muted">
                      {formatDate(r.created_at, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}
                    </td>
                    <td className="px-5 py-3">
                      <p className="font-medium text-ink">{r.filename}</p>
                      <p className="text-[13px] text-ink-muted">{r.message}</p>
                    </td>
                    <td className="px-5 py-3 text-right tabular-nums text-ink">{formatBytes(r.size_bytes)}</td>
                    <td className="px-5 py-3 text-right"><ImportStatus record={r} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryState>
      </Card>
    </>
  );
}
