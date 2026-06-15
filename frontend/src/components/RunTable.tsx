import { useQuery } from "@tanstack/react-query";
import { ExternalLink, History, Play } from "lucide-react";
import { api, RunRecord } from "../api";
import { StatusBadge } from "./StatusBadge";

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.round(diff / 1000);
  if (s < 60) return "Just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.round(h / 24);
  if (d === 1) return "Yesterday";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function formatDuration(run: RunRecord): string {
  const ms = new Date(run.updated_at).getTime() - new Date(run.created_at).getTime();
  const totalSec = Math.max(0, Math.round(ms / 1000));
  if (totalSec < 60) return `${totalSec}s`;
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  if (m < 60) return `${m}m ${s}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function shortId(runId: string): string {
  const clean = runId.replace(/-/g, "");
  if (clean.length <= 12) return clean;
  return `${clean.slice(0, 4)}-${clean.slice(4, 8)}-${clean.slice(8, 12)}`;
}

interface Props {
  pipeline: string;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}

function NoRunsState({ pipeline }: { pipeline: string }) {
  return (
    <div className="relative flex flex-col items-center justify-center min-h-[calc(100vh-14rem)] p-gutter">
      <div className="absolute inset-0 pointer-events-none overflow-hidden flex items-center justify-center">
        <div className="w-[600px] h-[600px] bg-primary/5 rounded-full blur-[120px]" />
      </div>
      <div className="relative z-10 flex flex-col items-center text-center max-w-md">
        <div className="mb-gutter relative">
          <div className="w-32 h-32 rounded-full border-2 border-dashed border-outline-variant flex items-center justify-center">
            <Play className="w-16 h-16 text-outline-variant opacity-60" strokeWidth={1.5} />
          </div>
          <div className="absolute -bottom-2 -right-2 bg-surface-container p-2 rounded-full border border-outline-variant">
            <History className="w-5 h-5 text-primary" />
          </div>
        </div>
        <h2 className="font-display-lg text-display-lg text-on-surface mb-stack-sm">No runs yet</h2>
        <p className="font-body-base text-body-base text-on-surface-variant mb-gutter px-4">
          Execute <span className="font-code-base text-code-base text-primary">{pipeline}</span> from
          Python to start recording runs. Your execution history will appear here.
        </p>
      </div>
      <div className="w-full mt-24 opacity-20 pointer-events-none max-w-3xl">
        <div className="border border-outline-variant rounded-lg overflow-hidden">
          <div className="bg-surface-container py-3 px-4 flex gap-12 border-b border-outline-variant">
            <span className="font-label-caps text-label-caps text-outline uppercase">Run ID</span>
            <span className="font-label-caps text-label-caps text-outline uppercase">Status</span>
            <span className="font-label-caps text-label-caps text-outline uppercase">Duration</span>
          </div>
          <div className="h-32 bg-surface-dim/40 flex items-center justify-center">
            <span className="font-code-sm text-code-sm text-outline-variant italic">
              Awaiting execution data…
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}

export function RunTable({ pipeline, selectedRunId, onSelect }: Props) {
  const { data, isLoading, isError } = useQuery<RunRecord[]>({
    queryKey: ["runs", pipeline],
    queryFn: () => api.runs(pipeline),
    refetchInterval: 5_000,
  });

  const hasRunSelected = selectedRunId !== null;

  return (
    <section
      className={`flex-1 pt-14 overflow-y-auto bg-surface-container-lowest transition-[margin] duration-200 ease-[cubic-bezier(0.4,0,0.2,1)] ml-60 ${
        hasRunSelected ? "mr-[400px]" : "mr-0"
      }`}
    >
      <div className="p-6">
        <div className="flex items-center justify-between mb-8">
          <div>
            <div className="flex items-center gap-2 text-on-surface-variant mb-1">
              <span className="font-label-caps text-label-caps">PIPELINE</span>
            </div>
            <h1 className="font-display-lg text-display-lg text-on-surface">{pipeline}</h1>
          </div>
        </div>

        {isLoading && (
          <div className="space-y-2">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-12 bg-surface-container-high rounded animate-pulse" />
            ))}
          </div>
        )}

        {isError && (
          <p className="text-error font-code-sm text-code-sm">Failed to load runs.</p>
        )}

        {!isLoading && !isError && data?.length === 0 && <NoRunsState pipeline={pipeline} />}

        {data && data.length > 0 && (
          <div className="bg-surface border border-outline-variant rounded-xl overflow-hidden shadow-sm">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="bg-surface-container text-on-surface-variant border-b border-outline-variant">
                  <th className="py-3 px-4 font-label-caps text-label-caps">RUN ID</th>
                  <th className="py-3 px-4 font-label-caps text-label-caps">STATUS</th>
                  <th className="py-3 px-4 font-label-caps text-label-caps text-right">
                    START TIME
                  </th>
                  <th className="py-3 px-4 font-label-caps text-label-caps text-right">
                    DURATION
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-outline-variant">
                {data.map((run) => {
                  const isSelected = selectedRunId === run.run_id;
                  const isRunning = run.status === "running";
                  return (
                    <tr
                      key={run.run_id}
                      onClick={() => onSelect(run.run_id)}
                      className={`hover:bg-surface-variant/50 transition-all duration-200 cursor-pointer group ${
                        isSelected ? "bg-primary-container/5" : ""
                      }`}
                      style={{ transitionProperty: "transform, background-color" }}
                      onMouseEnter={(e) => {
                        e.currentTarget.style.transform = "translateX(2px)";
                      }}
                      onMouseLeave={(e) => {
                        e.currentTarget.style.transform = "translateX(0)";
                      }}
                    >
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2">
                          <span
                            className={`font-code-base text-code-base ${
                              isRunning ? "text-primary" : "text-on-surface"
                            }`}
                          >
                            {shortId(run.run_id)}
                          </span>
                          <ExternalLink className="w-3.5 h-3.5 opacity-0 group-hover:opacity-100 transition-opacity text-on-surface-variant" />
                        </div>
                      </td>
                      <td className="py-3 px-4">
                        <StatusBadge status={run.status} />
                      </td>
                      <td
                        className="py-3 px-4 font-body-sm text-body-sm text-on-surface-variant text-right"
                        title={new Date(run.created_at).toLocaleString()}
                      >
                        {relativeTime(run.created_at)}
                      </td>
                      <td className="py-3 px-4 font-body-sm text-body-sm text-on-surface-variant text-right">
                        {formatDuration(run)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  );
}
