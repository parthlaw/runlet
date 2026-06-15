import { useQuery } from "@tanstack/react-query";
import { Clock } from "lucide-react";
import { api, RunRecord } from "../api";

// ---------------------------------------------------------------------------
// Status palette
// ---------------------------------------------------------------------------

const STATUS_DOT: Record<string, string> = {
  success:   "bg-status-success",
  failed:    "bg-status-failed",
  running:   "bg-status-running",
  cancelled: "bg-content-ghost",
};

const STATUS_BADGE: Record<string, string> = {
  success:   "bg-emerald-950/60 text-emerald-400 border-emerald-900/50",
  failed:    "bg-red-950/60 text-red-400 border-red-900/50",
  running:   "bg-amber-950/60 text-amber-400 border-amber-900/50",
  cancelled: "bg-surface-high text-content-ghost border-outline-strong",
};

// ---------------------------------------------------------------------------
// Formatters
// ---------------------------------------------------------------------------

function relativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const s = Math.round(diff / 1000);
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.round(h / 24)}d ago`;
}

function duration(run: RunRecord): string {
  const ms = new Date(run.updated_at).getTime() - new Date(run.created_at).getTime();
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function shortId(runId: string): string {
  return runId.length > 14 ? runId.slice(0, 14) + "…" : runId;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface Props {
  pipeline: string;
  selectedRunId: string | null;
  onSelect: (runId: string) => void;
}

export function RunList({ pipeline, selectedRunId, onSelect }: Props) {
  const { data, isLoading, isError } = useQuery<RunRecord[]>({
    queryKey: ["runs", pipeline],
    queryFn: () => api.runs(pipeline),
    refetchInterval: 5_000,
  });

  return (
    <div className="flex flex-col h-full bg-surface">
      {/* Header */}
      <div className="px-4 py-3 border-b border-outline-strong bg-surface-low shrink-0 flex items-baseline gap-2">
        <span className="text-[11px] uppercase tracking-widest text-content-muted font-semibold">Runs</span>
        <span className="text-xs text-content-dim font-mono truncate">{pipeline}</span>
        {data && (
          <span className="ml-auto text-[10px] text-content-ghost font-mono shrink-0">{data.length}</span>
        )}
      </div>

      {/* Loading skeletons */}
      {isLoading && (
        <div className="p-3 space-y-1.5">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-12 bg-surface-high rounded animate-pulse" />
          ))}
        </div>
      )}

      {isError && (
        <p className="px-4 py-3 text-red-400 text-xs font-mono">Failed to load runs.</p>
      )}

      {/* Run rows */}
      <div className="overflow-y-auto flex-1">
        {data?.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-3 h-full text-center px-6">
            <Clock className="w-7 h-7 text-content-ghost opacity-30" />
            <div>
              <p className="text-content-dim text-xs font-semibold">{pipeline}</p>
              <p className="text-content-ghost text-xs mt-0.5">No runs recorded yet</p>
              <p className="text-content-ghost/60 text-[11px] mt-1">
                Execute your pipeline from Python to see results here
              </p>
            </div>
          </div>
        )}

        {data?.map((run) => (
          <button
            key={run.run_id}
            onClick={() => onSelect(run.run_id)}
            className={`w-full text-left px-4 py-3 border-b border-outline-strong/40 transition-all duration-150 border-l-2 ${
              selectedRunId === run.run_id
                ? "bg-surface-high border-l-primary"
                : "hover:bg-surface-mid border-l-transparent"
            }`}
          >
            {/* Row 1: dot + badge + duration */}
            <div className="flex items-center gap-2">
              <span
                className={`shrink-0 w-1.5 h-1.5 rounded-full ${STATUS_DOT[run.status] ?? "bg-content-ghost"} ${
                  run.status === "running" ? "status-pulse" : ""
                }`}
              />
              <span
                className={`text-[10px] font-semibold px-1.5 py-px rounded border ${
                  STATUS_BADGE[run.status] ?? "text-content-ghost border-outline-strong"
                }`}
              >
                {run.status}
              </span>
              <span className="ml-auto font-mono text-[10px] text-content-muted shrink-0">
                {duration(run)}
              </span>
            </div>

            {/* Row 2: short run ID + relative time */}
            <div className="flex items-center gap-2 mt-1.5">
              <span className="font-mono text-[11px] text-content-dim truncate">
                {shortId(run.run_id)}
              </span>
              <span className="ml-auto font-mono text-[10px] text-content-ghost shrink-0">
                {relativeTime(run.created_at)}
              </span>
            </div>
          </button>
        ))}
      </div>
    </div>
  );
}
